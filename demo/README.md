# 可复现 Demo 数据

这个目录包含公开的冻结 Demo 数据库和校验清单。它不是生产数据库，也不会
调用 DeepSeek 或其他在线模型。

## 启动

在仓库根目录运行：

```powershell
python scripts/prepare_demo.py
```

然后按根目录 README 启动后端和前端。

登录信息：

```text
用户名：demo
密码：demo1234
```

Demo 账号只用于本地展示，所有访问者共享同一份初始学习数据。答题和学习
记录会写入本地 `backend/data/aiexamcoach.db`，重新执行准备脚本即可恢复初始
状态。

公开快照包含一门已经准备好的课程、知识点、题目、Evidence、题目映射和
练习状态。它的目的，是让代码审查者能够不配置 API Key，直接复现完整学生
练习路径。

当前快照清单见 [`manifest.json`](./manifest.json)。重新构建公开快照时，脚本
会重新计算数据库 SHA256，并在输出中打印课程、材料、知识点和题目数量。
