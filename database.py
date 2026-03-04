"""
Слой работы с базой данных (SQLite).
Все операции с бронированиями — здесь.
"""

import sqlite3
from datetime import date, datetime, timedelta
from typing import List, Optional, Tuple

DB_PATH = "quest_bot.db"


# ─── Инициализация ────────────────────────────────────────────

def init_db() -> None:
    """Создаёт таблицы, если их ещё нет."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS bookings (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id       INTEGER NOT NULL,
                username      TEXT    DEFAULT '',
                quest_id      TEXT    NOT NULL,
                booking_date  TEXT    NOT NULL,
                booking_time  TEXT    NOT NULL,
                client_name   TEXT    NOT NULL,
                client_phone  TEXT    NOT NULL,
                status        TEXT    NOT NULL DEFAULT 'confirmed',
                created_at    TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
                reminded_24h  INTEGER NOT NULL DEFAULT 0,
                reminded_2h   INTEGER NOT NULL DEFAULT 0
            )
        """)
        conn.commit()


# ─── Проверка слотов ──────────────────────────────────────────

def slot_is_available(quest_id: str, booking_date: str, booking_time: str) -> bool:
    """True если слот ещё не занят."""
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            """SELECT 1 FROM bookings
               WHERE quest_id=? AND booking_date=? AND booking_time=? AND status='confirmed'""",
            (quest_id, booking_date, booking_time),
        ).fetchone()
    return row is None


def get_booked_slots(quest_id: str, booking_date: str) -> List[str]:
    """Список занятых временных слотов для квеста на дату."""
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            """SELECT booking_time FROM bookings
               WHERE quest_id=? AND booking_date=? AND status='confirmed'""",
            (quest_id, booking_date),
        ).fetchall()
    return [r[0] for r in rows]


# ─── Создание бронирования ────────────────────────────────────

def create_booking(
    user_id: int,
    username: str,
    quest_id: str,
    booking_date: str,
    booking_time: str,
    name: str,
    phone: str,
) -> int:
    """Создаёт бронирование и возвращает его ID."""
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute(
            """INSERT INTO bookings
               (user_id, username, quest_id, booking_date, booking_time, client_name, client_phone)
               VALUES (?,?,?,?,?,?,?)""",
            (user_id, username or "", quest_id, booking_date, booking_time, name, phone),
        )
        return cur.lastrowid


# ─── Просмотр бронирований ────────────────────────────────────

def get_user_bookings(user_id: int) -> list:
    """Будущие бронирования пользователя."""
    with sqlite3.connect(DB_PATH) as conn:
        return conn.execute(
            """SELECT id, quest_id, booking_date, booking_time, status
               FROM bookings
               WHERE user_id=? AND booking_date >= ?
               ORDER BY booking_date, booking_time""",
            (user_id, date.today().isoformat()),
        ).fetchall()


def get_booking_by_id(booking_id: int, user_id: int) -> Optional[tuple]:
    """Полная запись бронирования (проверяет принадлежность пользователю)."""
    with sqlite3.connect(DB_PATH) as conn:
        return conn.execute(
            "SELECT * FROM bookings WHERE id=? AND user_id=?",
            (booking_id, user_id),
        ).fetchone()


# ─── Отмена ───────────────────────────────────────────────────

def cancel_booking(booking_id: int, user_id: int) -> bool:
    """Отменяет бронирование. Возвращает True при успехе."""
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute(
            """UPDATE bookings SET status='cancelled'
               WHERE id=? AND user_id=? AND status='confirmed'""",
            (booking_id, user_id),
        )
        return cur.rowcount > 0


# ─── Напоминания ──────────────────────────────────────────────

def get_bookings_needing_reminder() -> List[Tuple[str, tuple]]:
    """
    Возвращает [(тип_напоминания, строка_бронирования), ...]
    Тип: '24h' или '2h'
    Окно: ±30 минут от целевого времени
    """
    now = datetime.now()

    w24_start = now + timedelta(hours=23, minutes=30)
    w24_end   = now + timedelta(hours=24, minutes=30)
    w2_start  = now + timedelta(hours=1,  minutes=45)
    w2_end    = now + timedelta(hours=2,  minutes=15)

    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            """SELECT id, user_id, quest_id, booking_date, booking_time,
                      client_name, reminded_24h, reminded_2h
               FROM bookings
               WHERE status='confirmed' AND booking_date >= ?""",
            (date.today().isoformat(),),
        ).fetchall()

    result = []
    for row in rows:
        bk_id, uid, qid, bdate, btime, cname, r24, r2 = row
        try:
            bk_dt = datetime.strptime(f"{bdate} {btime}", "%Y-%m-%d %H:%M")
        except ValueError:
            continue

        if not r24 and w24_start <= bk_dt <= w24_end:
            result.append(("24h", row))
        elif not r2 and w2_start <= bk_dt <= w2_end:
            result.append(("2h", row))

    return result


def mark_reminded(booking_id: int, reminder_type: str) -> None:
    field = "reminded_24h" if reminder_type == "24h" else "reminded_2h"
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(f"UPDATE bookings SET {field}=1 WHERE id=?", (booking_id,))


# ─── Административные запросы ─────────────────────────────────

def get_today_bookings() -> list:
    """Все активные бронирования на сегодня."""
    with sqlite3.connect(DB_PATH) as conn:
        return conn.execute(
            """SELECT id, quest_id, booking_time, client_name, client_phone, username
               FROM bookings
               WHERE booking_date=? AND status='confirmed'
               ORDER BY quest_id, booking_time""",
            (date.today().isoformat(),),
        ).fetchall()


def get_week_bookings() -> list:
    """Все активные бронирования на 7 дней вперёд."""
    today = date.today()
    end   = today + timedelta(days=7)
    with sqlite3.connect(DB_PATH) as conn:
        return conn.execute(
            """SELECT id, quest_id, booking_date, booking_time, client_name, client_phone
               FROM bookings
               WHERE booking_date BETWEEN ? AND ? AND status='confirmed'
               ORDER BY booking_date, booking_time""",
            (today.isoformat(), end.isoformat()),
        ).fetchall()
