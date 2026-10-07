export function canStartPractice(item) {
  return item.practice_binding_status === "READY_PRIMARY_QUESTION" && item.practice_question_binding_ready === true;
}

export function availabilityText(status) {
  switch (status) {
    case "READY_PRIMARY_QUESTION":
      return "已有主关联真题，可开始练习";
    case "IMAGE_DEPENDENCY_NOT_SERVABLE":
      return "该真题依赖图片，当前版本暂不支持作答";
    case "NO_PRIMARY_QUESTION":
      return "当前暂无可直接练习的主关联真题";
    default:
      return "当前暂不可练习";
  }
}

export function startSessionRequest(studyUnitId) {
  return {
    path: `/study-units/${studyUnitId}/start`,
    method: "POST",
    body: JSON.stringify({ mode: "QUESTION_FIRST" }),
  };
}

export function startLearningRequest(studyUnitId) {
  return {
    path: `/study-units/${studyUnitId}/start`,
    method: "POST",
    body: JSON.stringify({}),
  };
}

export function startExplanationFirstRequest(studyUnitId) {
  return {
    path: `/study-units/${studyUnitId}/start`,
    method: "POST",
    body: JSON.stringify({ mode: "EXPLANATION_FIRST" }),
  };
}

export function nextQuestionPath(sessionId) {
  return `/learning-sessions/${sessionId}/next-question`;
}

export function answerRequest(questionId, payload) {
  return {
    path: `/questions/${questionId}/answer`,
    method: "POST",
    body: JSON.stringify(payload),
  };
}
