import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, date, time, timedelta
from typing import List, Dict, Tuple

import pandas as pd
import streamlit as st

# =========================
# Kai MB Mechanic Booking App (Streamlit + SQLite)
# Customer booking + Admin dashboard
# =========================

# ---------- BASIC SETTINGS (EDIT THESE) ----------
BUSINESS_NAME = "Kai MB Mechanic"
TAGLINE = "Mobile bike servicing & repairs — home, work, apartment."
CURRENCY = "AUD"

# Admin login (set env var KAI_ADMIN_PASSWORD for better security)
ADMIN_PASSWORD = os.getenv("KAI_ADMIN_PASSWORD", "kai123")  # CHANGE THIS AFTER TESTING

# Database file (created in the same folder as app.py)
DB_PATH = "bookings.db"

# Services (name -> base price)
SERVICES: Dict[str, int] = {
    "Safety Tune ($99)": 99,
    "Full Service ($189)": 189,
    "Family / 2 Bikes ($299)": 299,
    "Family / 3 Bikes ($420)": 420,
}

# Add-ons (optional, customer can tick; price added to total)
ADDONS: Dict[str, int] = {
    "Tube install labour (+$35)": 35,
    "Brake pads install labour (+$40)": 40,
    "Chain install labour (+$40)": 40,
    "Deep drivetrain clean (+$60)": 60,
    "E-bike inspection (+$40)": 40,
}

# Work schedule (Mon=0 ... Sun=6)
WORK_DAYS = {0, 1, 2, 3, 4, 5}  # Mon–Sat
DAY_START = time(9, 0)
DAY_END = time(18, 0)
SLOT_MINUTES = 60

# Booking limits
MAX_DAYS_AHEAD = 30
MIN_LEAD_TIME_MINUTES = 60  # block bookings too soon (e.g., within 60 minutes)

# Service area + travel fees (simple)
# Customer picks a zone; fee added to total
TRAVEL_ZONES: Dict[str, int] = {
    "Included area (no travel fee)": 0,
    "Outside area (+$20 travel fee)": 20,
    "Farther area (+$40 travel fee)": 40,
}

# Customer-facing policy
POLICY_NOTE = "Call-out included for included area. Parts are extra. You'll be contacted to confirm."
# ---------- END SETTINGS ----------


@dataclass
class Booking:
    created_at: str
    customer_name: str
    phone: str
    suburb: str
    address: str
    bike_type: str
    service_name: str
    service_price: int
    addons: str
    addons_price: int
    travel_zone: str
    travel_fee: int
    booking_date: str
    booking_time: str
    notes: str
    status: str = "new"


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            customer_name TEXT NOT NULL,
            phone TEXT NOT NULL,
            suburb TEXT NOT NULL,
            address TEXT NOT NULL,
            bike_type TEXT NOT NULL,
            service_name TEXT NOT NULL,
            service_price INTEGER NOT NULL,
            addons TEXT NOT NULL,
            addons_price INTEGER NOT NULL,
            travel_zone TEXT NOT NULL,
            travel_fee INTEGER NOT NULL,
            booking_date TEXT NOT NULL,
            booking_time TEXT NOT NULL,
            notes TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'new'
        )
        """
    )
    return conn


def normalize_phone(p: str) -> str:
    p = (p or "").strip()
    p = p.replace(" ", "").replace("-", "")
    return p


def is_valid_phone(p: str) -> bool:
    digits = "".join([c for c in p if c.isdigit()])
    return 9 <= len(digits) <= 12


def generate_slots(for_day: date) -> List[str]:
    if for_day.weekday() not in WORK_DAYS:
        return []
    slots = []
    dt = datetime.combine(for_day, DAY_START)
    end_dt = datetime.combine(for_day, DAY_END)
    while dt + timedelta(minutes=SLOT_MINUTES) <= end_dt:
        slots.append(dt.time().strftime("%H:%M"))
        dt += timedelta(minutes=SLOT_MINUTES)
    return slots


def slot_taken(conn: sqlite3.Connection, d: str, t: str) -> bool:
    cur = conn.execute(
        "SELECT COUNT(*) FROM bookings WHERE booking_date=? AND booking_time=? AND status!='cancelled'",
        (d, t),
    )
    return cur.fetchone()[0] > 0


def lead_time_ok(chosen_day: date, chosen_time_str: str) -> bool:
    try:
        hh, mm = chosen_time_str.split(":")
        chosen_dt = datetime.combine(chosen_day, time(int(hh), int(mm)))
    except Exception:
        return True
    return chosen_dt >= (datetime.now() + timedelta(minutes=MIN_LEAD_TIME_MINUTES))


def insert_booking(conn: sqlite3.Connection, b: Booking) -> None:
    conn.execute(
        """
        INSERT INTO bookings (
            created_at, customer_name, phone, suburb, address, bike_type,
            service_name, service_price, addons, addons_price, travel_zone, travel_fee,
            booking_date, booking_time, notes, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            b.created_at,
            b.customer_name,
            b.phone,
            b.suburb,
            b.address,
            b.bike_type,
            b.service_name,
            b.service_price,
            b.addons,
            b.addons_price,
            b.travel_zone,
            b.travel_fee,
            b.booking_date,
            b.booking_time,
            b.notes,
            b.status,
        ),
    )
    conn.commit()


def fetch_bookings(conn: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query(
        "SELECT * FROM bookings ORDER BY booking_date DESC, booking_time DESC, id DESC", conn
    )


def update_status(conn: sqlite3.Connection, booking_id: int, new_status: str) -> None:
    conn.execute("UPDATE bookings SET status=? WHERE id=?", (new_status, booking_id))
    conn.commit()


def money(n: int) -> str:
    return f"${n}"


# ---------------- UI ----------------
st.set_page_config(page_title=f"{BUSINESS_NAME} Booking", layout="centered")
st.title(f"🚲 {BUSINESS_NAME}")
st.caption(TAGLINE)
st.info(POLICY_NOTE)

conn = get_conn()

tabs = st.tabs(["Customer Booking", "Admin"])

# ---- Customer Booking ----
with tabs[0]:
    st.subheader("Book a service")

    colA, colB = st.columns(2)
    with colA:
        service_name = st.selectbox("Service", list(SERVICES.keys()))
    with colB:
        st.write("")
        st.write(f"**Base price:** {money(SERVICES[service_name])} ({CURRENCY})")

    travel_zone = st.selectbox("Travel zone", list(TRAVEL_ZONES.keys()))
    travel_fee = TRAVEL_ZONES[travel_zone]
    if travel_fee:
        st.write(f"**Travel fee:** {money(travel_fee)}")

    addons_selected = st.multiselect("Optional add-ons", list(ADDONS.keys()))
    addons_price = sum(ADDONS[a] for a in addons_selected)

    total = SERVICES[service_name] + travel_fee + addons_price
    st.write(f"### Total (labour + travel + add-ons): {money(total)} {CURRENCY}")
    st.caption("Parts are extra if needed — confirmed before fitting.")

    st.divider()

    min_day = date.today()
    max_day = date.today() + timedelta(days=MAX_DAYS_AHEAD)
    booking_day = st.date_input("Preferred date", value=min_day, min_value=min_day, max_value=max_day)

    slots = generate_slots(booking_day)
    if not slots:
        st.warning("No slots on this day. Try another date.")
        booking_time = None
    else:
        free_slots = [s for s in slots if not slot_taken(conn, booking_day.isoformat(), s)]
        if MIN_LEAD_TIME_MINUTES > 0:
            free_slots = [s for s in free_slots if lead_time_ok(booking_day, s)]
        if not free_slots:
            st.warning("No available slots left for this day. Try another date.")
            booking_time = None
        else:
            booking_time = st.selectbox("Time slot", free_slots)

    st.divider()

    customer_name = st.text_input("Your name *")
    phone = st.text_input("Phone *")
    suburb = st.text_input("Suburb *")
    address = st.text_input("Address (optional but recommended)")
    bike_type = st.selectbox("Bike type", ["Road", "MTB", "Hybrid", "E-bike", "Kids", "Other"])
    notes = st.text_area("Notes (optional)", placeholder="Issues, special requests, gate codes, etc.")

    consent = st.checkbox("I confirm details are correct. I understand parts (if needed) are extra.")
    if st.button("Submit booking", type="primary", disabled=(booking_time is None)):
        p = normalize_phone(phone)
        errors = []
        if not customer_name.strip():
            errors.append("Name is required.")
        if not p:
            errors.append("Phone is required.")
        elif not is_valid_phone(p):
            errors.append("Phone number looks invalid.")
        if not suburb.strip():
            errors.append("Suburb is required.")
        if not consent:
            errors.append("You must confirm the details.")
        if booking_time and slot_taken(conn, booking_day.isoformat(), booking_time):
            errors.append("That time just got booked. Pick another slot.")

        if errors:
            for e in errors:
                st.error(e)
        else:
            b = Booking(
                created_at=datetime.now().isoformat(timespec="seconds"),
                customer_name=customer_name.strip(),
                phone=p,
                suburb=suburb.strip(),
                address=address.strip(),
                bike_type=bike_type,
                service_name=service_name,
                service_price=SERVICES[service_name],
                addons=", ".join(addons_selected) if addons_selected else "None",
                addons_price=addons_price,
                travel_zone=travel_zone,
                travel_fee=travel_fee,
                booking_date=booking_day.isoformat(),
                booking_time=booking_time,
                notes=notes.strip() if notes else "",
                status="new",
            )
            insert_booking(conn, b)
            st.success("Booking submitted ✅ Kai will contact you to confirm.")
            st.info("Tip: Screenshot this page for your reference.")


# ---- Admin ----
with tabs[1]:
    st.subheader("Admin")
    pw = st.text_input("Admin password", type="password")

    if pw and pw == ADMIN_PASSWORD:
        st.success("Logged in ✅")

        df = fetch_bookings(conn)
        if df.empty:
            st.info("No bookings yet.")
        else:
            col1, col2, col3 = st.columns(3)
            with col1:
                status_filter = st.multiselect(
                    "Status filter",
                    options=["new", "confirmed", "done", "cancelled"],
                    default=["new", "confirmed"],
                )
            with col2:
                date_from = st.date_input("From date", value=date.today() - timedelta(days=14))
            with col3:
                date_to = st.date_input("To date", value=date.today() + timedelta(days=1))

            df_view = df.copy()
            if status_filter:
                df_view = df_view[df_view["status"].isin(status_filter)]
            df_view = df_view[
                (pd.to_datetime(df_view["booking_date"]) >= pd.to_datetime(date_from))
                & (pd.to_datetime(df_view["booking_date"]) <= pd.to_datetime(date_to))
            ]

            # Add computed total column
            df_view["total"] = df_view["service_price"] + df_view["addons_price"] + df_view["travel_fee"]

            st.dataframe(df_view, use_container_width=True, hide_index=True)

            st.divider()
            st.markdown("### Update booking status")
            booking_ids = df["id"].tolist()
            selected_id = st.selectbox("Booking ID", booking_ids)
            new_status = st.selectbox("New status", ["new", "confirmed", "done", "cancelled"])

            if st.button("Update status"):
                update_status(conn, int(selected_id), new_status)
                st.success("Status updated.")
                st.rerun()

            st.divider()
            st.markdown("### Export CSV")
            csv = df.to_csv(index=False).encode("utf-8")
            st.download_button(
                "Download bookings.csv",
                data=csv,
                file_name="bookings.csv",
                mime="text/csv",
            )

            st.divider()
            st.markdown("### Quick totals (filtered view)")
            if not df_view.empty:
                st.write(f"Bookings shown: **{len(df_view)}**")
                st.write(f"Estimated labour+travel+addons total: **{money(int(df_view['total'].sum()))} {CURRENCY}**")
    elif pw:
        st.error("Wrong password.")
    else:
        st.info("Enter password to manage bookings.")
