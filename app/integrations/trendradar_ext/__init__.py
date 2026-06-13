"""扩展 TrendRadar 的代码集中区。

铁律：禁止修改 trendradar/ 目录下任何文件。
对 TrendRadar 的扩展（如 Redis pub/sub sender、配置注入）一律放在这里，
通过 register_*() 函数在 FastAPI startup 中注入。
"""
