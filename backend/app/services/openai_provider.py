"""OpenAI-compatible provider. Activated only when AEC_AI_PROVIDER=openai_compatible
and AEC_OPENAI_API_KEY is set. Uses the same pipeline contract as the heuristic
provider but drives a hosted model via structured JSON prompts.
"""
import json
from typing import Callable, List

import httpx

from app.services.ai_provider import AIProvider
from app.services.semantic_shadow import (
    SemanticProviderError,
    SemanticProviderHTTPError,
    SemanticProviderNetworkError,
    SemanticProviderResponseError,
    SemanticProviderSchemaError,
    SemanticProviderTruncatedResponse,
    SemanticProviderTimeout,
    normalize_provider_response,
    parse_provider_json,
    sanitize_provider_text,
    MAX_ALIASES_PER_CANDIDATE,
    MAX_CANDIDATES_PER_SECTION,
    MAX_EVIDENCE_EXCERPT_CHARS,
    MAX_EVIDENCE_REFS_PER_CANDIDATE,
    MAX_LEARNING_OBJECTIVE_CHARS,
)


SEMANTIC_MAX_OUTPUT_TOKENS = 3000
SEMANTIC_TIMEOUT_CONFIG = {
    "connect_timeout": 10.0,
    "read_timeout": 90.0,
    "write_timeout": 15.0,
    "pool_timeout": 15.0,
    "total_timeout": None,
}


class OpenAICompatibleProvider(AIProvider):
    def __init__(self, settings, credential_accessor=None):
        # Keep provider configuration on the instance, but resolve the
        # credential only when constructing a request. This avoids retaining
        # the secret as provider state and keeps it out of repr/log/cache data.
        self._credential_accessor = credential_accessor or (lambda: settings.openai_api_key)
        self.base_url = settings.openai_base_url
        self.model = settings.openai_model
        self.timeout = httpx.Timeout(
            SEMANTIC_TIMEOUT_CONFIG["read_timeout"],
            connect=SEMANTIC_TIMEOUT_CONFIG["connect_timeout"],
            read=SEMANTIC_TIMEOUT_CONFIG["read_timeout"],
            write=SEMANTIC_TIMEOUT_CONFIG["write_timeout"],
            pool=SEMANTIC_TIMEOUT_CONFIG["pool_timeout"],
        )
        # The project uses raw httpx rather than an OpenAI SDK. Explicitly set
        # transport retries to zero so one paid semantic invocation is one
        # transport invocation, including on timeout/error.
        self.http = httpx.Client(transport=httpx.HTTPTransport(retries=0), timeout=self.timeout)
        self.last_response_metadata = {
            "provider_response_received": False,
            "http_status_code": None,
        }
        self.last_request_metadata = {}
        self.request_profile = {
            "thinking_mode": "disabled",
            "max_output_tokens": SEMANTIC_MAX_OUTPUT_TOKENS,
            "connect_timeout": SEMANTIC_TIMEOUT_CONFIG["connect_timeout"],
            "read_timeout": SEMANTIC_TIMEOUT_CONFIG["read_timeout"],
            "write_timeout": SEMANTIC_TIMEOUT_CONFIG["write_timeout"],
            "pool_timeout": SEMANTIC_TIMEOUT_CONFIG["pool_timeout"],
            "total_timeout": SEMANTIC_TIMEOUT_CONFIG["total_timeout"],
            "sdk_max_retries": 0,
            "response_format": {"type": "json_object"},
            "stream": False,
        }

    def analyze_material(self, text: str, material_type: str) -> dict:
        system = (
            "You are the Course Brain for an exam-review product. Extract from the "
            "course material: (1) study_units: list of {{title, evidence}} that are coherent, "
            "learnable knowledge points. evidence must be a short verbatim source excerpt "
            "which supports that exact title; omit a unit if no excerpt exists. "
            "learnable knowledge points; (2) questions: list of {{content, type, answer, "
            "explanation, knowledge_titles, evidence}} if the text contains exam questions; "
            "knowledge_titles must name only concepts supported by the question, and evidence "
            "must be the verbatim question block; (3) evidence: list of "
            "{{type, content}}. Respond only with a JSON object matching this schema. "
            "Do not invent teacher-specific claims not present in the text."
        )
        payload = {"model": self.model, "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": text[:12000]},
        ], "temperature": 0.2}
        try:
            credential = self._request_api_key()
            r = self.http.post(
                self.base_url.rstrip("/") + "/chat/completions",
                headers={"Authorization": f"Bearer {credential}"},
                json=payload,
            )
            r.raise_for_status()
            content = r.json()["choices"][0]["message"]["content"]
            # strip fences
            content = content.strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[-1].rsplit("```", 1)[0]
            data = json.loads(content)
            return {
                "study_units": data.get("study_units", []),
                "questions": data.get("questions", []),
                "evidence": data.get("evidence", []),
            }
        except Exception:
            # Per docs/08: AI failure must not block the course. Fall back to heuristic.
            from app.services.ai_provider import HeuristicProvider

            return HeuristicProvider().analyze_material(text, material_type)

    def _request_api_key(self):
        """Resolve the local credential only for the current HTTP request."""
        try:
            credential = self._credential_accessor()
        except Exception:
            raise SemanticProviderError("PROVIDER_CONFIG_ERROR: API key unavailable") from None
        if not isinstance(credential, str) or not credential.strip():
            raise SemanticProviderError("PROVIDER_CONFIG_ERROR: API key unavailable")
        return credential

    def _request_json(self, system: str, user: str, *, temperature: float = 0.0, on_raw_response: Callable[[dict], None] | None = None) -> dict:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": self.request_profile["max_output_tokens"],
            "response_format": self.request_profile["response_format"],
            "stream": self.request_profile["stream"],
            # Raw httpx sends the OpenAI-compatible extension directly. This
            # is equivalent to SDK extra_body={"thinking": {"type": "disabled"}}.
            "thinking": {"type": "disabled"},
        }
        self.last_response_metadata = {
            "provider_response_received": False,
            "http_status_code": None,
        }
        self.last_request_metadata = {
            "system_prompt_char_count": len(system),
            "user_prompt_char_count": len(user),
            "total_prompt_char_count": len(system) + len(user),
        }
        credential = self._request_api_key()
        try:
            response = self.http.post(
                self.base_url.rstrip("/") + "/chat/completions",
                headers={"Authorization": f"Bearer {credential}"},
                json=payload,
            )
            self.last_response_metadata = {
                "provider_response_received": True,
                "http_status_code": response.status_code,
            }
            if response.is_error:
                try:
                    error_body = response.json()
                except ValueError:
                    error_body = {}
                error = error_body.get("error", {}) if isinstance(error_body, dict) else {}
                error = error if isinstance(error, dict) else {}
                provider_message = error.get("message") or response.text or None
                raise SemanticProviderHTTPError(
                    response.status_code,
                    provider_error_code=sanitize_provider_text(error.get("code"), api_key=credential) or None,
                    provider_error_type=sanitize_provider_text(error.get("type"), api_key=credential) or None,
                    sanitized_provider_message=sanitize_provider_text(provider_message, api_key=credential),
                )
            try:
                body = response.json()
            except ValueError:
                raise SemanticProviderResponseError("PROVIDER_RESPONSE_ERROR: invalid JSON HTTP response") from None
            try:
                choice = body["choices"][0]
                content = choice["message"]["content"]
            except (KeyError, IndexError, TypeError, AttributeError):
                raise SemanticProviderResponseError("PROVIDER_RESPONSE_ERROR: missing chat completion content") from None
            if content is None:
                raise SemanticProviderResponseError("PROVIDER_RESPONSE_ERROR: missing chat completion content") from None
            finish_reason = choice.get("finish_reason") if isinstance(choice, dict) else None
            content = str(content)
            self.last_response_metadata.update(
                {
                    "finish_reason": finish_reason,
                    "raw_response_char_count": len(content),
                    "sanitized_response_preview": sanitize_provider_text(content, api_key=credential),
                    "response_truncated": finish_reason == "length",
                }
            )
            if on_raw_response is not None:
                on_raw_response({
                    "raw_response_text": sanitize_provider_text(content, api_key=credential, limit=2_000_000),
                    "raw_response_char_count": len(content),
                    "http_status": response.status_code,
                    "finish_reason": finish_reason,
                    "usage": body.get("usage"),
                    "top_level_parsed_keys": sorted(str(key) for key in body.keys()) if isinstance(body, dict) else [],
                })
            normalized = normalize_provider_response(content)
            try:
                data = parse_provider_json(normalized)
            except SemanticProviderSchemaError as exc:
                if finish_reason == "length":
                    raise SemanticProviderTruncatedResponse(
                        "PROVIDER_TRUNCATED_RESPONSE: provider response ended at max output length"
                    ) from None
                raise exc
            # The caller persists this sanitized raw semantic payload before
            # applying its own schema/eligibility validation.  Never return
            # the request headers or the unsanitized credential-bearing text.
            return {
                "data": data,
                "usage": body.get("usage"),
                "raw_response_text": sanitize_provider_text(content, api_key=credential, limit=2_000_000),
                "raw_response_char_count": len(content),
                "top_level_parsed_keys": sorted(str(key) for key in body.keys()) if isinstance(body, dict) else [],
                "http_status": response.status_code,
                "finish_reason": finish_reason,
            }
        except httpx.ConnectTimeout:
            raise SemanticProviderTimeout("CONNECT_TIMEOUT") from None
        except httpx.ReadTimeout:
            raise SemanticProviderTimeout("READ_TIMEOUT") from None
        except httpx.WriteTimeout:
            raise SemanticProviderTimeout("WRITE_TIMEOUT") from None
        except httpx.PoolTimeout:
            raise SemanticProviderTimeout("POOL_TIMEOUT") from None
        except httpx.TimeoutException:
            raise SemanticProviderTimeout("TOTAL_TIMEOUT") from None
        except (SemanticProviderHTTPError, SemanticProviderResponseError, SemanticProviderSchemaError):
            raise
        except httpx.RequestError as exc:
            raise SemanticProviderNetworkError(f"PROVIDER_NETWORK_ERROR: {type(exc).__name__}") from None
        except Exception as exc:
            # Semantic shadow runs must never silently masquerade as heuristic.
            raise SemanticProviderError(f"PROVIDER_ERROR: {type(exc).__name__}") from None

    def smoke_test(self) -> dict:
        result = self._request_json(
            "Respond only with a JSON object containing the boolean field ok.",
            '{"task":"connectivity_smoke_test","ok":true}',
        )
        data = result["data"]
        if not isinstance(data, dict) or data.get("ok") is not True:
            raise SemanticProviderSchemaError("SCHEMA_ERROR: structured smoke response did not match the contract")
        return {"usage": result.get("usage")}

    def extract_knowledge_points(self, chunk: dict) -> dict:
        system = (
            "You are a bounded Course Brain semantic extractor. Return only a JSON object "
            "with a candidates array. Each candidate must contain exactly: candidate_id, "
            "canonical_name_zh, canonical_name_en, aliases, parent_hint_zh, parent_hint_en, "
            "learning_objective_zh, evidence_refs, confidence, decision. Each evidence_ref "
            "must contain material_id, source_start, source_end, excerpt. Extract only "
            "learnable database concepts supported by the supplied section. Do not turn each "
            "sentence into a concept. Keep standard English terminology and provide a Chinese "
            "student-facing name. Do not invent concepts absent from the section. ACCEPT needs "
            "a verbatim excerpt and exact offsets within the full persisted material text; use REVIEW "
            "or ABSTAIN when support or offsets are uncertain. Deduplicate parent/child concepts "
            "carefully and make learning_objective_zh describe what a student can do after study. "
            "Return ONLY one valid UTF-8 JSON object: no prose before or after, no Markdown, no "
            "```json fence, no comments, and no trailing text. The top-level shape must be exactly "
            "{\"candidates\":[{\"candidate_id\":\"example-id\",\"canonical_name_zh\":\"示例知识点\","
            "\"canonical_name_en\":\"Example Concept\",\"aliases\":[],\"parent_hint_zh\":null,"
            "\"parent_hint_en\":null,\"learning_objective_zh\":\"能够解释该知识点。\","
            "\"evidence_refs\":[{\"material_id\":\"material-id\",\"source_start\":0,"
            "\"source_end\":1,\"excerpt\":\"原文摘录\"}],\"confidence\":0.0,"
            "\"decision\":\"REVIEW\"}]} . Replace the example values with supported concepts "
            "from the supplied section and preserve the exact field names. "
            f"Return no more than {MAX_CANDIDATES_PER_SECTION} candidates; do not split concepts "
            f"to fill the limit. Each aliases array has at most {MAX_ALIASES_PER_CANDIDATE} items, "
            f"each candidate has at most {MAX_EVIDENCE_REFS_PER_CANDIDATE} evidence_refs, each "
            f"evidence excerpt is at most {MAX_EVIDENCE_EXCERPT_CHARS} characters, and "
            f"learning_objective_zh is at most {MAX_LEARNING_OBJECTIVE_CHARS} Chinese characters. "
            "Do not include explanations, examples, exam_focus, common_mistakes, reasoning, "
            "or chain of thought."
        )
        user = json.dumps(
            {
                "material_id": chunk["material_id"],
                "source_start": chunk["source_start"],
                "source_end": chunk["source_end"],
                "language": chunk["language"],
                "source_text": chunk["source_text"],
            },
            ensure_ascii=False,
        )
        result = self._request_json(system, user, temperature=0.1)
        data = result["data"]
        if not isinstance(data, dict) or not isinstance(data.get("candidates"), list):
            raise SemanticProviderSchemaError("SCHEMA_ERROR: semantic response did not contain a candidates array")
        return {"candidates": data["candidates"], "usage": result.get("usage")}
