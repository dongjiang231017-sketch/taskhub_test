"""工程包初始化：开发环境用 PyMySQL 替代 mysqlclient 时满足 Django 版本检查。"""

try:
    import pymysql

    pymysql.version_info = (2, 2, 1, "final", 0)
    pymysql.install_as_MySQLdb()
except ImportError:
    pass
