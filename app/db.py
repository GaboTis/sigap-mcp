"""Conexión a SQL Server SIGAP — SOLO LECTURA.

Las credenciales vienen de .env (nunca hardcodeadas).
La app y el MCP usan esta única función.
"""
import os

import pyodbc
from dotenv import load_dotenv

load_dotenv()


def get_conn():
    """Devuelve una conexión pyodbc a SIGAP (lectura)."""
    server = os.getenv('DB_SERVER')
    database = os.getenv('DB_DATABASE', 'SIGAP')
    auth = os.getenv('DB_AUTH_TYPE', 'SQL')
    driver = os.getenv('MSSQL_DRIVER', 'ODBC Driver 17 for SQL Server')

    if auth == 'SQL':
        conn_str = (
            f'DRIVER={{{driver}}};SERVER={server};DATABASE={database};'
            f'UID={os.getenv("DB_USERNAME", "")};PWD={os.getenv("DB_PASSWORD", "")};'
            'TrustServerCertificate=yes'
        )
    else:
        conn_str = (
            f'DRIVER={{{driver}}};SERVER={server};DATABASE={database};'
            'Trusted_Connection=yes;TrustServerCertificate=yes'
        )
    return pyodbc.connect(conn_str, timeout=30)
