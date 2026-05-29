#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
InternPath - Production Database Migration Script (SQLite -> PostgreSQL)
Usage:
  export DATABASE_URL="postgresql://user:pass@host:port/dbname"
  python deploy/migrate_to_postgres.py
"""

import os
import sys
import uuid
import sqlite3
import psycopg2
from datetime import datetime

# Add project root to sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(PROJECT_ROOT)

from config import Config
from database import Database

def main():
    print("=========================================================")
    print("          InternPath - Production Database Migrator       ")
    print("=========================================================")

    # 1. Load Configurations
    postgres_url = os.getenv("DATABASE_URL")
    if not postgres_url:
        print("[ERROR] DATABASE_URL environment variable is not configured!")
        print("Please export DATABASE_URL and run again.")
        print("Example: export DATABASE_URL=\"postgresql://postgres:password@localhost:5432/job_dashboard\"")
        sys.exit(1)

    sqlite_db_path = os.getenv("SQLITE_DB_PATH", Config.DB_PATH)
    if not os.path.exists(sqlite_db_path):
        print(f"[ERROR] Source SQLite database file not found at: {sqlite_db_path}")
        sys.exit(1)

    print(f"[INFO] Source SQLite: {sqlite_db_path}")
    print(f"[INFO] Target PostgreSQL: {postgres_url.split('@')[-1]} (password masked)")

    # 2. Establish connections
    try:
        lite_conn = sqlite3.connect(sqlite_db_path)
        lite_cursor = lite_conn.cursor()
    except Exception as e:
        print(f"[ERROR] Failed to connect to SQLite: {e}")
        sys.exit(1)

    try:
        pg_conn = psycopg2.connect(postgres_url)
        pg_cursor = pg_conn.cursor()
    except Exception as e:
        print(f"[ERROR] Failed to connect to PostgreSQL: {e}")
        lite_conn.close()
        sys.exit(1)

    # 3. Initialize PostgreSQL Schema
    print("\n--- [Step 1/4] Initializing PostgreSQL Schema ---")
    try:
        # Force is_postgres check inside DB class
        os.environ["DATABASE_URL"] = postgres_url
        db = Database()
        db.init_db()
        print("[SUCCESS] Schema initialization complete.")
    except Exception as e:
        print(f"[ERROR] Failed to initialize Postgres Schema: {e}")
        lite_conn.close()
        pg_conn.close()
        sys.exit(1)

    # 4. Migrate Data
    print("\n--- [Step 2/4] Migrating Data (Integer -> UUID conversion) ---")
    
    tables_order = [
        "users", "registered_devices", "analysis_records", "drafts", "user_settings",
        "model_configs", "model_config_assignments", "model_usage_logs", "admin_audit_logs",
        "embeddings", "jd_records", "course_records", "job_postings", "salary_snapshots",
        "fit_exam_attempts", "analysis_task", "analysis_report", "claim_check_result",
        "knowledge_document", "knowledge_chunk", "analysis_workflow_log", 
        "analysis_quality_evaluation", "sessions", "email_verification_codes", "star_stories"
    ]

    try:
        pg_cursor.execute("SET session_replication_role = 'replica';")
        
        # User ID mapping from Integer to UUID
        user_id_map = {}
        
        for table in tables_order:
            # Check if table exists in SQLite
            lite_cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
            if not lite_cursor.fetchone():
                print(f"[SKIP] Table '{table}' does not exist in SQLite.")
                continue
                
            # Clear target Postgres table before migration
            pg_cursor.execute(f"TRUNCATE TABLE {table} CASCADE;")
            
            # Fetch column structure from SQLite
            lite_cursor.execute(f"PRAGMA table_info({table})")
            columns_info = lite_cursor.fetchall()
            column_names = [col[1] for col in columns_info]
            
            cols_str = ", ".join(column_names)
            lite_cursor.execute(f"SELECT {cols_str} FROM {table}")
            rows = lite_cursor.fetchall()
            
            if not rows:
                print(f" - '{table}': 0 rows (Skipped migration)")
                continue
                
            mapped_rows = []
            if table == "users":
                # Convert user PK from integer to UUID string
                for r in rows:
                    r_list = list(r)
                    old_id = r_list[0]
                    new_id = str(uuid.uuid4())
                    user_id_map[old_id] = new_id
                    r_list[0] = new_id
                    mapped_rows.append(tuple(r_list))
            else:
                # Map any column ending with 'user_id' or 'admin_id' using user_id_map
                user_cols = [i for i, col in enumerate(column_names) if col.endswith("user_id") or col.endswith("admin_id")]
                if user_cols:
                    for r in rows:
                        r_list = list(r)
                        for col_idx in user_cols:
                            old_val = r_list[col_idx]
                            if old_val is not None:
                                if old_val not in user_id_map:
                                    user_id_map[old_val] = str(uuid.uuid4())
                                r_list[col_idx] = user_id_map[old_val]
                        mapped_rows.append(tuple(r_list))
                else:
                    mapped_rows = rows
            
            # Convert Boolean values for PostgreSQL
            pg_cursor.execute(
                """
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name=%s AND data_type='boolean'
                """, 
                (table.lower(),)
            )
            bool_cols = {row[0].lower() for row in pg_cursor.fetchall()}
            bool_indices = [i for i, col in enumerate(column_names) if col.lower() in bool_cols]
            
            if bool_indices:
                mapped_rows_bool = []
                for r in mapped_rows:
                    r_list = list(r)
                    for idx in bool_indices:
                        val = r_list[idx]
                        if val is not None:
                            r_list[idx] = bool(val)
                    mapped_rows_bool.append(tuple(r_list))
                mapped_rows = mapped_rows_bool
                    
            placeholders = ", ".join(["%s"] * len(column_names))
            insert_query = f"INSERT INTO {table} ({cols_str}) VALUES ({placeholders})"
            pg_cursor.executemany(insert_query, mapped_rows)
            print(f" - '{table}': Migrated {len(mapped_rows)} rows.")
            
            # Reset integer auto-increment PK sequences in Postgres
            pg_cursor.execute(
                "SELECT column_default FROM information_schema.columns WHERE table_name=%s AND column_name='id'",
                (table.lower(),)
            )
            res = pg_cursor.fetchone()
            if res and res[0] and 'nextval' in res[0]:
                seq_name = res[0].split("'")[1]
                pg_cursor.execute(f"SELECT COALESCE(max(id), 1) FROM {table}")
                max_id = pg_cursor.fetchone()[0]
                pg_cursor.execute("SELECT setval(%s, %s)", (seq_name, max_id))
                print(f"   * Reset sequence '{seq_name}' to {max_id}")
                
        pg_conn.commit()
        print("[SUCCESS] Data migration complete.")
        
    except Exception as e:
        pg_conn.rollback()
        print(f"[ERROR] Migration failed: {e}")
        lite_conn.close()
        pg_conn.close()
        sys.exit(1)

    # 5. Data Count Verification
    print("\n--- [Step 3/4] Data Integrity Verification ---")
    mismatches = 0
    for table in tables_order:
        lite_cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
        if not lite_cursor.fetchone():
            continue
        lite_cursor.execute(f"SELECT COUNT(*) FROM {table}")
        lite_count = lite_cursor.fetchone()[0]
        pg_cursor.execute(f"SELECT COUNT(*) FROM {table}")
        pg_count = pg_cursor.fetchone()[0]
        status = "OK" if lite_count == pg_count else "MISMATCH"
        print(f"Table '{table}': SQLite={lite_count} | PostgreSQL={pg_count} | [{status}]")
        if lite_count != pg_count:
            mismatches += 1

    lite_conn.close()
    pg_conn.close()

    print("\n--- [Step 4/4] Summary ---")
    if mismatches > 0:
        print(f"[WARNING] Migration completed with {mismatches} table count mismatches! Please check logs.")
        sys.exit(1)
    else:
        print("[SUCCESS] Database migration completed perfectly with 100% data integrity!")
        print("You can now safely configure DATABASE_URL in your cloud .env file to run on PostgreSQL.")
        sys.exit(0)

if __name__ == "__main__":
    main()
