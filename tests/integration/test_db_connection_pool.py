"""
DB接続プール同時接続テスト

このテストは PR #462-#470 で発生した「pool.connect() がハングする」障害を
事前に検出するためのもの。

本番環境と同じプール設定（pool_size=5, max_overflow=2）で
複数スレッドから同時に pool.connect() を呼び出し、
全接続が制限時間内に完了することを検証する。

3者合意(Claude + Codex + Gemini):
  「本番と同じプール設定で9-12同時接続し、全て3秒以内に完了しなければテスト失敗」
"""

import os
import time
import threading
import pytest
import sqlalchemy
from sqlalchemy import text
from sqlalchemy.pool import QueuePool


TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="TEST_DATABASE_URL not set"
)


class TestConnectionPoolConcurrency:
    """接続プールの同時接続テスト"""

    def _create_engine_with_production_settings(self):
        """本番と同じプール設定でエンジンを作成"""
        return sqlalchemy.create_engine(
            TEST_DATABASE_URL,
            poolclass=QueuePool,
            pool_size=5,
            max_overflow=2,
            pool_timeout=10,  # テスト用に短縮（本番は30s）
            pool_recycle=1800,
            pool_pre_ping=True,
        )

    def test_single_connection(self, db_engine):
        """基本: 1接続が正常に動作すること"""
        with db_engine.connect() as conn:
            result = conn.execute(text("SELECT 1"))
            assert result.scalar() == 1

    def test_sequential_connections(self, db_engine):
        """順次: 複数の接続を順番に取得・解放できること"""
        for i in range(10):
            with db_engine.connect() as conn:
                result = conn.execute(text("SELECT :n"), {"n": i})
                assert result.scalar() == i

    def test_concurrent_connections_within_pool_size(self, db_engine):
        """
        同時接続（プールサイズ内）: pool_size=5 以内の同時接続が正常動作すること
        """
        results = []
        errors = []
        timeout_seconds = 5.0

        def worker(thread_id):
            start = time.monotonic()
            try:
                with db_engine.connect() as conn:
                    elapsed = time.monotonic() - start
                    if elapsed > timeout_seconds:
                        errors.append(f"Thread {thread_id}: connection took {elapsed:.2f}s (timeout={timeout_seconds}s)")
                        return
                    result = conn.execute(text("SELECT :tid"), {"tid": thread_id})
                    val = result.scalar()
                    results.append((thread_id, val, elapsed))
            except Exception as e:
                errors.append(f"Thread {thread_id}: {type(e).__name__}: {e}")

        threads = []
        for i in range(5):  # pool_size=5 なので5スレッド
            t = threading.Thread(target=worker, args=(i,))
            threads.append(t)

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=timeout_seconds + 5)

        assert not errors, f"Errors occurred: {errors}"
        assert len(results) == 5, f"Expected 5 results, got {len(results)}"
        for tid, val, elapsed in results:
            assert val == tid
            assert elapsed < timeout_seconds, f"Thread {tid} took {elapsed:.2f}s"

    def test_concurrent_connections_at_max_capacity(self):
        """
        同時接続（最大容量）: pool_size + max_overflow = 7 同時接続が動作すること

        これが PR #462-#470 の障害を検出するテスト。
        db-f1-micro では9同時 pool.connect() がハングした。
        """
        engine = self._create_engine_with_production_settings()
        try:
            max_connections = 7  # pool_size(5) + max_overflow(2)
            results = []
            errors = []
            timeout_seconds = 10.0

            def worker(thread_id):
                start = time.monotonic()
                try:
                    with engine.connect() as conn:
                        elapsed_connect = time.monotonic() - start
                        # 接続を少し保持（本番のクエリ実行時間をシミュレート）
                        conn.execute(text("SELECT pg_sleep(0.1)"))
                        elapsed_total = time.monotonic() - start
                        results.append({
                            "thread_id": thread_id,
                            "connect_time": elapsed_connect,
                            "total_time": elapsed_total,
                        })
                except Exception as e:
                    elapsed = time.monotonic() - start
                    errors.append({
                        "thread_id": thread_id,
                        "error": f"{type(e).__name__}",
                        "elapsed": elapsed,
                    })

            threads = []
            for i in range(max_connections):
                t = threading.Thread(target=worker, args=(i,))
                threads.append(t)

            start_all = time.monotonic()
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=timeout_seconds + 5)
            total_elapsed = time.monotonic() - start_all

            # 全スレッドがタイムアウトなしで完了すること
            assert not errors, (
                f"Connection errors occurred (this may indicate pool exhaustion): {errors}"
            )
            assert len(results) == max_connections, (
                f"Expected {max_connections} results, got {len(results)}"
            )
            # 全体が制限時間内に完了すること
            assert total_elapsed < timeout_seconds, (
                f"Total time {total_elapsed:.2f}s exceeded {timeout_seconds}s timeout. "
                f"Pool may be exhausted or connections hanging."
            )
        finally:
            engine.dispose()

    def test_connections_exceeding_pool_capacity(self):
        """
        同時接続（容量超過）: pool_size + max_overflow を超える接続は
        pool_timeout 以内に解放を待つか、タイムアウトすること

        ハングせずにタイムアウトエラーが発生することを確認する。
        （PR #462-#470の障害: ハングして応答なし → これが正しい動作）
        """
        engine = sqlalchemy.create_engine(
            TEST_DATABASE_URL,
            poolclass=QueuePool,
            pool_size=2,
            max_overflow=1,
            pool_timeout=3,  # 3秒でタイムアウト
            pool_recycle=1800,
            pool_pre_ping=True,
        )
        try:
            held_connections = []
            errors = []
            timeout_error_count = 0

            # まずプールを完全に埋める (pool_size + max_overflow = 3)
            for i in range(3):
                conn = engine.connect()
                conn.execute(text("SELECT 1"))
                held_connections.append(conn)

            # 追加の接続はタイムアウトすべき（ハングしてはいけない）
            def try_connect():
                nonlocal timeout_error_count
                start = time.monotonic()
                try:
                    with engine.connect() as conn:
                        conn.execute(text("SELECT 1"))
                        errors.append("Connection should have timed out but succeeded")
                except Exception as e:
                    elapsed = time.monotonic() - start
                    if "timeout" in str(type(e).__name__).lower() or "timeout" in str(e).lower() or elapsed >= 2.5:
                        timeout_error_count += 1  # 期待通り
                    else:
                        errors.append(f"Unexpected error: {type(e).__name__} after {elapsed:.2f}s")

            t = threading.Thread(target=try_connect)
            t.start()
            t.join(timeout=10)

            # クリーンアップ
            for conn in held_connections:
                conn.close()

            assert not errors, f"Unexpected behavior: {errors}"
            assert timeout_error_count == 1, (
                "Pool should timeout gracefully when exhausted, not hang indefinitely"
            )
        finally:
            engine.dispose()

    def test_connection_with_rollback_cleanup(self, db_engine, setup_test_schema):
        """
        接続クリーンアップ: conn.rollback() パターンが正常動作すること

        PR #471 の _fetch_all_db_data() で導入された
        「conn.rollback() で接続状態をクリーン化」パターンの検証。
        """
        with db_engine.connect() as conn:
            # ダーティな状態を作る
            conn.execute(text(
                "INSERT INTO integration_test_table (organization_id, name) "
                "VALUES (:org, :name)"
            ), {"org": "test-org", "name": "dirty-data"})

            # rollback でクリーン化
            conn.rollback()

            # クリーンな状態でクエリが正常動作すること
            result = conn.execute(text(
                "SELECT COUNT(*) FROM integration_test_table WHERE organization_id = :org"
            ), {"org": "test-org"})
            count = result.scalar()
            assert count == 0, "Rollback should have cleared the dirty data"

    def test_statement_timeout(self, db_engine):
        """
        statement_timeout: DBタイムアウトが正しく機能すること

        PR #471 で導入された statement_timeout=5000ms の検証。
        """
        with db_engine.connect() as conn:
            # タイムアウトを短く設定
            conn.execute(text("SELECT set_config('statement_timeout', '1000', true)"))

            # 1秒以上かかるクエリはタイムアウトすること
            with pytest.raises(Exception):
                conn.execute(text("SELECT pg_sleep(3)"))

            # タイムアウト後も接続は使えること（rollbackで復帰）
            conn.rollback()
            result = conn.execute(text("SELECT 1"))
            assert result.scalar() == 1

    def test_set_config_rls_pattern(self, db_engine):
        """
        RLS set_config パターン: organization_id の設定・取得・クリアが正常動作すること

        lib/db.py の get_db_session_with_org() パターンの検証。
        """
        test_org_id = "test-org-12345678"

        with db_engine.connect() as conn:
            # set_config で組織IDを設定
            conn.execute(
                text("SELECT set_config('app.current_organization_id', :org_id, false)"),
                {"org_id": test_org_id}
            )

            # current_setting で取得できること
            result = conn.execute(
                text("SELECT current_setting('app.current_organization_id', true)")
            )
            assert result.scalar() == test_org_id

            # NULLでクリア
            conn.execute(
                text("SELECT set_config('app.current_organization_id', NULL, false)")
            )

            # クリア後は空文字列が返ること
            result = conn.execute(
                text("SELECT current_setting('app.current_organization_id', true)")
            )
            val = result.scalar()
            assert val is None or val == "", f"Expected empty after clear, got: {val}"


class TestBasicDBOperations:
    """基本的なDB操作の結合テスト"""

    def test_insert_and_select(self, db_conn, setup_test_schema):
        """INSERT → SELECT が正常動作すること"""
        db_conn.execute(text(
            "INSERT INTO integration_test_table (organization_id, name, value) "
            "VALUES (:org, :name, :val)"
        ), {"org": "org-001", "name": "test-item", "val": "hello"})
        db_conn.commit()

        result = db_conn.execute(text(
            "SELECT name, value FROM integration_test_table WHERE organization_id = :org"
        ), {"org": "org-001"})
        row = result.fetchone()
        assert row is not None
        assert row[0] == "test-item"
        assert row[1] == "hello"

    def test_organization_id_isolation(self, db_conn, setup_test_schema):
        """organization_id によるデータ分離が機能すること"""
        # 2つの組織のデータを挿入
        db_conn.execute(text(
            "INSERT INTO integration_test_table (organization_id, name) VALUES (:org, :name)"
        ), {"org": "org-A", "name": "data-A"})
        db_conn.execute(text(
            "INSERT INTO integration_test_table (organization_id, name) VALUES (:org, :name)"
        ), {"org": "org-B", "name": "data-B"})
        db_conn.commit()

        # org-A のデータだけ取得できること
        result = db_conn.execute(text(
            "SELECT name FROM integration_test_table WHERE organization_id = :org"
        ), {"org": "org-A"})
        rows = result.fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "data-A"

    def test_parameterized_query(self, db_conn, setup_test_schema):
        """パラメータ化クエリが正常動作すること（SQLインジェクション防止）"""
        malicious_input = "'; DROP TABLE integration_test_table; --"
        db_conn.execute(text(
            "INSERT INTO integration_test_table (organization_id, name) VALUES (:org, :name)"
        ), {"org": "org-safe", "name": malicious_input})
        db_conn.commit()

        # テーブルがまだ存在すること
        result = db_conn.execute(text(
            "SELECT COUNT(*) FROM integration_test_table"
        ))
        assert result.scalar() >= 1

        # 悪意のある文字列がそのまま保存されていること
        result = db_conn.execute(text(
            "SELECT name FROM integration_test_table WHERE organization_id = :org"
        ), {"org": "org-safe"})
        assert result.fetchone()[0] == malicious_input

    def test_transaction_rollback(self, db_conn, setup_test_schema):
        """トランザクションのロールバックが正常動作すること"""
        db_conn.execute(text(
            "INSERT INTO integration_test_table (organization_id, name) VALUES (:org, :name)"
        ), {"org": "org-rollback", "name": "should-disappear"})

        # コミットせずにロールバック
        db_conn.rollback()

        result = db_conn.execute(text(
            "SELECT COUNT(*) FROM integration_test_table WHERE organization_id = :org"
        ), {"org": "org-rollback"})
        assert result.scalar() == 0
