from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path


ROLE_ADMIN = "admin"
ROLE_MANAGER = "manager"
ROLE_DEVELOPER = "developer"


@dataclass(frozen=True)
class StaffMember:
    telegram_id: int
    role: str
    username: str | None
    added_at: str


@dataclass(frozen=True)
class UserLink:
    telegram_id: int
    user_id: int
    email: str
    username: str | None
    role: str


@dataclass(frozen=True)
class FineRecord:
    id: int
    telegram_id: int
    amount: float
    reason: str
    shift_id: int | None
    created_by: int
    created_at: str


@dataclass(frozen=True)
class ShiftEarning:
    shift_id: int
    telegram_id: int
    langame_user_id: int
    shift_start: str | None
    shift_stop: str | None
    bar_sales: float
    bar_bonus: float
    fixed_salary: float
    gross_amount: float
    sales_count: int
    synced_at: str


@dataclass(frozen=True)
class BalanceSettlement:
    id: int
    telegram_id: int
    amount: float
    cycle_key: str
    settled_at: str


@dataclass(frozen=True)
class BarSaleCredit:
    sale_id: int
    telegram_id: int
    shift_id: int
    sale_amount: float
    bonus_amount: float
    credited_at: str


class Storage:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS admin_links (
                telegram_id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL,
                email TEXT NOT NULL,
                username TEXT,
                role TEXT NOT NULL DEFAULT 'admin'
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS fines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_user_id INTEGER NOT NULL,
                amount REAL NOT NULL,
                reason TEXT NOT NULL,
                shift_id INTEGER,
                created_by INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                cancelled INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS staff_roles (
                telegram_id INTEGER PRIMARY KEY,
                role TEXT NOT NULL,
                username TEXT,
                added_at TEXT NOT NULL
            )
            """
        )
        self._ensure_column("admin_links", "role", "TEXT NOT NULL DEFAULT 'admin'")
        self._ensure_column("fines", "telegram_id", "INTEGER")
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS shift_earnings (
                shift_id INTEGER PRIMARY KEY,
                telegram_id INTEGER NOT NULL,
                langame_user_id INTEGER NOT NULL,
                shift_start TEXT,
                shift_stop TEXT,
                bar_sales REAL NOT NULL,
                bar_bonus REAL NOT NULL,
                fixed_salary REAL NOT NULL,
                gross_amount REAL NOT NULL,
                sales_count INTEGER NOT NULL DEFAULT 0,
                synced_at TEXT NOT NULL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS balance_settlements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER NOT NULL,
                amount REAL NOT NULL,
                cycle_key TEXT NOT NULL,
                settled_at TEXT NOT NULL,
                UNIQUE(telegram_id, cycle_key)
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS bar_sale_credits (
                sale_id INTEGER PRIMARY KEY,
                telegram_id INTEGER NOT NULL,
                shift_id INTEGER NOT NULL,
                sale_amount REAL NOT NULL,
                bonus_amount REAL NOT NULL,
                credited_at TEXT NOT NULL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS shift_notifications (
                shift_id INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                notified_at TEXT NOT NULL,
                PRIMARY KEY (shift_id, event_type)
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS bot_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS half_month_notifications (
                cycle_key TEXT PRIMARY KEY,
                notified_at TEXT NOT NULL
            )
            """
        )
        self._migrate_fines_to_telegram_id()
        self._conn.commit()

    def _migrate_fines_to_telegram_id(self) -> None:
        self._conn.execute(
            """
            UPDATE fines
            SET telegram_id = (
                SELECT telegram_id FROM admin_links
                WHERE admin_links.user_id = fines.admin_user_id
                  AND admin_links.user_id != 0
            )
            WHERE telegram_id IS NULL
            """
        )

    def _ensure_column(self, table: str, column: str, definition: str) -> None:
        columns = {
            row["name"]
            for row in self._conn.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if column not in columns:
            self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    @staticmethod
    def admin_name(link: UserLink | None, telegram_id: int | None = None) -> str:
        if link:
            return link.username or str(link.telegram_id)
        if telegram_id is not None:
            return str(telegram_id)
        return "—"

    def resolve_bot_admin(self, query: str) -> UserLink | None:
        normalized = query.strip()
        if not normalized:
            return None

        if normalized.isdigit():
            link = self.get_link(int(normalized))
            if link and link.role == ROLE_ADMIN:
                return link
            return None

        needle = normalized.lower()
        admins = self.list_links(ROLE_ADMIN)

        for link in admins:
            if link.username and link.username.lower() == needle:
                return link

        for link in admins:
            if link.username and needle in link.username.lower():
                return link

        return None

    def register_admin(self, telegram_id: int, username: str) -> None:
        self.link_admin(
            telegram_id=telegram_id,
            user_id=0,
            email=f"pending_{telegram_id}@local",
            username=username.strip(),
            role=ROLE_ADMIN,
        )

    def remove_admin(self, telegram_id: int) -> bool:
        cursor = self._conn.execute(
            "DELETE FROM admin_links WHERE telegram_id = ? AND role = ?",
            (telegram_id, ROLE_ADMIN),
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def attach_langame(
        self,
        telegram_id: int,
        user_id: int,
        email: str,
        langame_username: str | None = None,
    ) -> bool:
        existing = self.get_link(telegram_id)
        if not existing:
            return False
        username = existing.username or langame_username or email
        self.link_admin(
            telegram_id=telegram_id,
            user_id=user_id,
            email=email,
            username=username,
            role=existing.role,
        )
        return True

    def link_admin(
        self,
        telegram_id: int,
        user_id: int,
        email: str,
        username: str | None,
        role: str = ROLE_ADMIN,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO admin_links (telegram_id, user_id, email, username, role)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(telegram_id) DO UPDATE SET
                user_id = excluded.user_id,
                email = excluded.email,
                username = excluded.username,
                role = excluded.role
            """,
            (telegram_id, user_id, email, username, role),
        )
        self._conn.commit()

    def register_staff_manager(self, telegram_id: int, username: str) -> None:
        created_at = datetime.now().isoformat(timespec="seconds")
        self._conn.execute(
            """
            INSERT INTO staff_roles (telegram_id, role, username, added_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(telegram_id) DO UPDATE SET
                role = excluded.role,
                username = excluded.username
            """,
            (telegram_id, ROLE_MANAGER, username.strip(), created_at),
        )
        self._conn.commit()

    def remove_staff_manager(self, telegram_id: int) -> bool:
        cursor = self._conn.execute(
            "DELETE FROM staff_roles WHERE telegram_id = ? AND role = ?",
            (telegram_id, ROLE_MANAGER),
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def is_staff_manager(self, telegram_id: int) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM staff_roles WHERE telegram_id = ? AND role = ?",
            (telegram_id, ROLE_MANAGER),
        ).fetchone()
        return row is not None

    def list_staff_managers(self) -> list[StaffMember]:
        rows = self._conn.execute(
            """
            SELECT * FROM staff_roles
            WHERE role = ?
            ORDER BY username, telegram_id
            """,
            (ROLE_MANAGER,),
        ).fetchall()
        return [
            StaffMember(
                telegram_id=int(row["telegram_id"]),
                role=str(row["role"]),
                username=row["username"],
                added_at=str(row["added_at"]),
            )
            for row in rows
        ]

    def set_role(self, telegram_id: int, role: str) -> bool:
        cursor = self._conn.execute(
            "UPDATE admin_links SET role = ? WHERE telegram_id = ?",
            (role, telegram_id),
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def get_link(self, telegram_id: int) -> UserLink | None:
        row = self._conn.execute(
            "SELECT * FROM admin_links WHERE telegram_id = ?",
            (telegram_id,),
        ).fetchone()
        if not row:
            return None
        return UserLink(
            telegram_id=int(row["telegram_id"]),
            user_id=int(row["user_id"]),
            email=str(row["email"]),
            username=row["username"],
            role=str(row["role"] or ROLE_ADMIN),
        )

    def get_link_by_user_id(self, user_id: int) -> UserLink | None:
        if user_id == 0:
            return None
        row = self._conn.execute(
            "SELECT * FROM admin_links WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        if not row:
            return None
        return UserLink(
            telegram_id=int(row["telegram_id"]),
            user_id=int(row["user_id"]),
            email=str(row["email"]),
            username=row["username"],
            role=str(row["role"] or ROLE_ADMIN),
        )

    def list_links(self, role: str | None = None) -> list[UserLink]:
        if role:
            rows = self._conn.execute(
                "SELECT * FROM admin_links WHERE role = ? ORDER BY username, email",
                (role,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM admin_links ORDER BY role DESC, username, email"
            ).fetchall()
        return [
            UserLink(
                telegram_id=int(row["telegram_id"]),
                user_id=int(row["user_id"]),
                email=str(row["email"]),
                username=row["username"],
                role=str(row["role"] or ROLE_ADMIN),
            )
            for row in rows
        ]

    def add_fine(
        self,
        telegram_id: int,
        amount: float,
        reason: str,
        created_by: int,
        shift_id: int | None = None,
    ) -> int:
        created_at = datetime.now().isoformat(timespec="seconds")
        cursor = self._conn.execute(
            """
            INSERT INTO fines (
                admin_user_id, telegram_id, amount, reason, shift_id, created_by, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (telegram_id, telegram_id, amount, reason, shift_id, created_by, created_at),
        )
        self._conn.commit()
        return int(cursor.lastrowid)

    def cancel_fine(self, fine_id: int) -> bool:
        cursor = self._conn.execute(
            "UPDATE fines SET cancelled = 1 WHERE id = ? AND cancelled = 0",
            (fine_id,),
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def get_fine(self, fine_id: int) -> FineRecord | None:
        row = self._conn.execute(
            "SELECT * FROM fines WHERE id = ?",
            (fine_id,),
        ).fetchone()
        if not row:
            return None
        return self._row_to_fine(row)

    def list_fines(
        self,
        telegram_id: int | None = None,
        *,
        active_only: bool = True,
        limit: int = 20,
    ) -> list[FineRecord]:
        query = "SELECT * FROM fines WHERE 1=1"
        params: list[object] = []
        if telegram_id is not None:
            query += " AND telegram_id = ?"
            params.append(telegram_id)
        if active_only:
            query += " AND cancelled = 0"
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        rows = self._conn.execute(query, params).fetchall()
        return [self._row_to_fine(row) for row in rows]

    def sum_fines(self, telegram_id: int, shift_id: int | None = None) -> float:
        if shift_id is not None:
            row = self._conn.execute(
                """
                SELECT COALESCE(SUM(amount), 0) AS total
                FROM fines
                WHERE telegram_id = ? AND shift_id = ? AND cancelled = 0
                """,
                (telegram_id, shift_id),
            ).fetchone()
        else:
            row = self._conn.execute(
                """
                SELECT COALESCE(SUM(amount), 0) AS total
                FROM fines
                WHERE telegram_id = ? AND cancelled = 0
                """,
                (telegram_id,),
            ).fetchone()
        return float(row["total"])

    def sum_fines_for_shifts(self, telegram_id: int, shift_ids: list[int]) -> float:
        if not shift_ids:
            return 0.0
        placeholders = ",".join("?" for _ in shift_ids)
        row = self._conn.execute(
            f"""
            SELECT COALESCE(SUM(amount), 0) AS total
            FROM fines
            WHERE telegram_id = ? AND cancelled = 0
              AND (shift_id IN ({placeholders}) OR shift_id IS NULL)
            """,
            [telegram_id, *shift_ids],
        ).fetchone()
        return float(row["total"])

    def has_shift_earning(self, shift_id: int) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM shift_earnings WHERE shift_id = ?",
            (shift_id,),
        ).fetchone()
        return row is not None

    def get_shift_earning(self, shift_id: int) -> ShiftEarning | None:
        row = self._conn.execute(
            "SELECT * FROM shift_earnings WHERE shift_id = ?",
            (shift_id,),
        ).fetchone()
        if not row:
            return None
        return self._row_to_shift_earning(row)

    def add_shift_earning(
        self,
        shift_id: int,
        telegram_id: int,
        langame_user_id: int,
        shift_start: str | None,
        shift_stop: str | None,
        bar_sales: float,
        bar_bonus: float,
        fixed_salary: float,
        gross_amount: float,
        sales_count: int,
    ) -> None:
        synced_at = datetime.now().isoformat(timespec="seconds")
        self._conn.execute(
            """
            INSERT INTO shift_earnings (
                shift_id, telegram_id, langame_user_id, shift_start, shift_stop,
                bar_sales, bar_bonus, fixed_salary, gross_amount, sales_count, synced_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                shift_id,
                telegram_id,
                langame_user_id,
                shift_start,
                shift_stop,
                bar_sales,
                bar_bonus,
                fixed_salary,
                gross_amount,
                sales_count,
                synced_at,
            ),
        )
        self._conn.commit()

    def list_shift_earnings(
        self,
        telegram_id: int,
        date_from: date | None = None,
        date_to: date | None = None,
        *,
        limit: int = 500,
    ) -> list[ShiftEarning]:
        query = "SELECT * FROM shift_earnings WHERE telegram_id = ?"
        params: list[object] = [telegram_id]
        if date_from is not None:
            query += " AND date(substr(shift_start, 1, 10)) >= date(?)"
            params.append(date_from.isoformat())
        if date_to is not None:
            query += " AND date(substr(shift_start, 1, 10)) <= date(?)"
            params.append(date_to.isoformat())
        query += " ORDER BY shift_start DESC LIMIT ?"
        params.append(limit)
        rows = self._conn.execute(query, params).fetchall()
        return [self._row_to_shift_earning(row) for row in rows]

    def count_shift_earnings(self, telegram_id: int) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) AS total FROM shift_earnings WHERE telegram_id = ?",
            (telegram_id,),
        ).fetchone()
        return int(row["total"])

    def sum_shift_earnings(
        self,
        telegram_id: int,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> float:
        query = "SELECT COALESCE(SUM(gross_amount), 0) AS total FROM shift_earnings WHERE telegram_id = ?"
        params: list[object] = [telegram_id]
        if date_from is not None:
            query += " AND date(substr(shift_start, 1, 10)) >= date(?)"
            params.append(date_from.isoformat())
        if date_to is not None:
            query += " AND date(substr(shift_start, 1, 10)) <= date(?)"
            params.append(date_to.isoformat())
        row = self._conn.execute(query, params).fetchone()
        return float(row["total"])

    def sum_fines_between(self, telegram_id: int, date_from: date, date_to: date) -> float:
        row = self._conn.execute(
            """
            SELECT COALESCE(SUM(amount), 0) AS total
            FROM fines
            WHERE telegram_id = ? AND cancelled = 0
              AND date(substr(created_at, 1, 10)) >= date(?)
              AND date(substr(created_at, 1, 10)) <= date(?)
            """,
            (telegram_id, date_from.isoformat(), date_to.isoformat()),
        ).fetchone()
        return float(row["total"])

    def has_bar_sale_credit(self, sale_id: int) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM bar_sale_credits WHERE sale_id = ?",
            (sale_id,),
        ).fetchone()
        return row is not None

    def add_bar_sale_credit(
        self,
        sale_id: int,
        telegram_id: int,
        shift_id: int,
        sale_amount: float,
        bonus_amount: float,
    ) -> bool:
        if self.has_bar_sale_credit(sale_id):
            return False
        credited_at = datetime.now().isoformat(timespec="seconds")
        self._conn.execute(
            """
            INSERT INTO bar_sale_credits (
                sale_id, telegram_id, shift_id, sale_amount, bonus_amount, credited_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (sale_id, telegram_id, shift_id, sale_amount, bonus_amount, credited_at),
        )
        self._conn.commit()
        return True

    def sum_bar_sale_credits(
        self,
        telegram_id: int,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> float:
        query = """
            SELECT COALESCE(SUM(bonus_amount), 0) AS total
            FROM bar_sale_credits
            WHERE telegram_id = ?
        """
        params: list[object] = [telegram_id]
        if date_from is not None:
            query += " AND date(substr(credited_at, 1, 10)) >= date(?)"
            params.append(date_from.isoformat())
        if date_to is not None:
            query += " AND date(substr(credited_at, 1, 10)) <= date(?)"
            params.append(date_to.isoformat())
        row = self._conn.execute(query, params).fetchone()
        return float(row["total"])

    def sum_bar_sale_credits_for_shift(self, telegram_id: int, shift_id: int) -> float:
        row = self._conn.execute(
            """
            SELECT COALESCE(SUM(bonus_amount), 0) AS total
            FROM bar_sale_credits
            WHERE telegram_id = ? AND shift_id = ?
            """,
            (telegram_id, shift_id),
        ).fetchone()
        return float(row["total"])

    def has_shift_notification(self, shift_id: int, event_type: str) -> bool:
        row = self._conn.execute(
            """
            SELECT 1 FROM shift_notifications
            WHERE shift_id = ? AND event_type = ?
            """,
            (shift_id, event_type),
        ).fetchone()
        return row is not None

    def mark_shift_notification(self, shift_id: int, event_type: str) -> bool:
        if self.has_shift_notification(shift_id, event_type):
            return False
        notified_at = datetime.now().isoformat(timespec="seconds")
        self._conn.execute(
            """
            INSERT INTO shift_notifications (shift_id, event_type, notified_at)
            VALUES (?, ?, ?)
            """,
            (shift_id, event_type, notified_at),
        )
        self._conn.commit()
        return True

    def has_balance_settlement(self, telegram_id: int, cycle_key: str) -> bool:
        row = self._conn.execute(
            """
            SELECT 1 FROM balance_settlements
            WHERE telegram_id = ? AND cycle_key = ?
            """,
            (telegram_id, cycle_key),
        ).fetchone()
        return row is not None

    def add_balance_settlement(
        self,
        telegram_id: int,
        amount: float,
        cycle_key: str,
        settled_at: str,
    ) -> int | None:
        if self.has_balance_settlement(telegram_id, cycle_key):
            return None
        cursor = self._conn.execute(
            """
            INSERT INTO balance_settlements (telegram_id, amount, cycle_key, settled_at)
            VALUES (?, ?, ?, ?)
            """,
            (telegram_id, amount, cycle_key, settled_at),
        )
        self._conn.commit()
        return int(cursor.lastrowid)

    def sum_settlements(self, telegram_id: int) -> float:
        row = self._conn.execute(
            """
            SELECT COALESCE(SUM(amount), 0) AS total
            FROM balance_settlements
            WHERE telegram_id = ?
            """,
            (telegram_id,),
        ).fetchone()
        return float(row["total"])

    @staticmethod
    def _row_to_shift_earning(row: sqlite3.Row) -> ShiftEarning:
        return ShiftEarning(
            shift_id=int(row["shift_id"]),
            telegram_id=int(row["telegram_id"]),
            langame_user_id=int(row["langame_user_id"]),
            shift_start=row["shift_start"],
            shift_stop=row["shift_stop"],
            bar_sales=float(row["bar_sales"]),
            bar_bonus=float(row["bar_bonus"]),
            fixed_salary=float(row["fixed_salary"]),
            gross_amount=float(row["gross_amount"]),
            sales_count=int(row["sales_count"]),
            synced_at=str(row["synced_at"]),
        )

    @staticmethod
    def _row_to_fine(row: sqlite3.Row) -> FineRecord:
        telegram_id = row["telegram_id"]
        if telegram_id is None:
            telegram_id = row["admin_user_id"]
        return FineRecord(
            id=int(row["id"]),
            telegram_id=int(telegram_id),
            amount=float(row["amount"]),
            reason=str(row["reason"]),
            shift_id=row["shift_id"],
            created_by=int(row["created_by"]),
            created_at=str(row["created_at"]),
        )

    def get_bot_setting(self, key: str) -> str | None:
        row = self._conn.execute(
            "SELECT value FROM bot_settings WHERE key = ?",
            (key,),
        ).fetchone()
        return str(row["value"]) if row else None

    def set_bot_setting(self, key: str, value: str) -> None:
        self._conn.execute(
            """
            INSERT INTO bot_settings (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )
        self._conn.commit()

    def has_half_month_notification(self, cycle_key: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM half_month_notifications WHERE cycle_key = ?",
            (cycle_key,),
        ).fetchone()
        return row is not None

    def mark_half_month_notification(self, cycle_key: str) -> None:
        from datetime import datetime

        self._conn.execute(
            """
            INSERT OR IGNORE INTO half_month_notifications (cycle_key, notified_at)
            VALUES (?, ?)
            """,
            (cycle_key, datetime.now().isoformat(timespec="seconds")),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
