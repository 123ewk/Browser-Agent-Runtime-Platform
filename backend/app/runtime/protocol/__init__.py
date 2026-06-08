"""Runtime ↔ Worker 通信协议

设计要点:
- 协议优先(Protocol First): 所有通信格式在此冻结,Worker 和 Runtime 独立开发
- JSON Lines: Worker 的 stdout 是 RuntimeEvent 流, stdin 是 Command 流
- 每条消息一行 JSON,不含换行符,解码时按行拆分
- 版本号嵌入每条 RuntimeEvent.version,Worker 启动时 Runtime 校验兼容性
"""
