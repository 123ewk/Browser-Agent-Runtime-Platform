"""Repository 层 —— 数据访问,接收 AsyncSession,返回 Pydantic DTO。

禁止反向依赖:api → service → repository → model。
"""
