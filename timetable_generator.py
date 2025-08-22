# timetable_generator.py
# Requirements: streamlit, pandas, openpyxl, xlsxwriter
# pip install streamlit pandas openpyxl xlsxwriter

import streamlit as st
import pandas as pd
from datetime import datetime, timedelta, time
from io import BytesIO
import random

st.set_page_config(page_title="Automatic Timetable Generator", layout="wide")

# ------------------------- UI HELPERS -------------------------
def time_slots(start_t: time, period_minutes: int, periods_per_day: int):
    """Return list of 'HH:MM - HH:MM' strings for each period."""
    slots = []
    cursor = datetime.combine(datetime.today(), start_t)
    for _ in range(periods_per_day):
        end = cursor + timedelta(minutes=period_minutes)
        slots.append(f"{cursor.strftime('%H:%M')}–{end.strftime('%H:%M')}")
        cursor = end
    return slots

def seed_subject_rows():
    return pd.DataFrame(
        [
            {"Subject": "Math", "Type": "Theory", "Periods_per_Week": 4, "Is_Long_Session": False, "Session_Length": 1},
            {"Subject": "Physics Lab", "Type": "Lab/Project", "Periods_per_Week": 3, "Is_Long_Session": True, "Session_Length": 3},
        ]
    )

def sanitize_subjects(df: pd.DataFrame):
    """Clean and normalize the subject config table."""
    df = df.fillna({"Subject": "", "Type": "Theory", "Periods_per_Week": 0, "Is_Long_Session": False, "Session_Length": 1})
    df["Subject"] = df["Subject"].astype(str).str.strip()
    df["Type"] = df["Type"].astype(str).str.strip()
    # Force ints
    for col in ["Periods_per_Week", "Session_Length"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)
    df["Is_Long_Session"] = df["Is_Long_Session"].astype(bool)
    # Normalize: if Type is Lab/Project, Is_Long_Session True by default
    df.loc[df["Type"].str.lower().str.contains("lab") | df["Type"].str.lower().str.contains("project"), "Is_Long_Session"] = True
    # Remove empty rows
    df = df[df["Subject"] != ""].copy()
    return df

# ------------------------- SCHEDULER -------------------------
def build_requirements(subject_df: pd.DataFrame):
    """
    Returns:
      singles: dict subj -> remaining single periods
      blocks: list of (subject, session_length) repeated until total periods match
    """
    singles = {}
    blocks = []
    for _, row in subject_df.iterrows():
        subj = row["Subject"]
        if row.get("Is_Long_Session", False) and row.get("Session_Length", 1) > 1:
            # Calculate how many blocks required based on total periods and session length
            total_periods = int(row.get("Periods_per_Week", 0))
            if total_periods > 0:
                num_blocks = total_periods // int(row["Session_Length"])
                for _ in range(num_blocks):
                    blocks.append((subj, int(row["Session_Length"])))
        else:
            singles[subj] = singles.get(subj, 0) + int(row.get("Periods_per_Week", 0))
    return singles, blocks

def can_place_block(day_row, start_idx, length):
    """Check if a block of given length fits contiguously into the day's row."""
    if start_idx + length > len(day_row):
        return False
    return all(day_row[i] == "" for i in range(start_idx, start_idx + length))

def place_blocks(tt, blocks, days, periods_per_day):
    """Place long sessions (blocks) first."""
    random.shuffle(blocks)
    blocks.sort(key=lambda b: -b[1])  # Longest first
    last_day_for_subject = {}

    for subj, length in blocks:
        placed = False
        day_order = list(range(days))
        random.shuffle(day_order)
        if subj in last_day_for_subject:
            ld = last_day_for_subject[subj]
            day_order = day_order[day_order.index(ld):] + day_order[:day_order.index(ld)]

        for d in day_order:
            for p in range(periods_per_day):
                if can_place_block(tt[d], p, length):
                    for k in range(p, p + length):
                        tt[d][k] = subj + " (Long Session)"
                    last_day_for_subject[subj] = d
                    placed = True
                    break
            if placed:
                break

        if not placed:
            return False
    return True

def pick_single_subject(remaining, used_today):
    """Pick a subject with remaining > 0 and not used today."""
    candidates = [(s, c) for s, c in remaining.items() if c > 0 and s not in used_today]
    if not candidates:
        return None
    max_rem = max(c for _, c in candidates)
    top = [s for s, c in candidates if c == max_rem]
    return random.choice(top)

def fill_singles(tt, singles, days, periods_per_day):
    for d in range(days):
        used_today = set([s.replace(" (Long Session)", "") for s in tt[d] if s])
        for p in range(periods_per_day):
            if tt[d][p] != "":
                continue
            subj = pick_single_subject(singles, used_today)
            if subj is None:
                continue
            tt[d][p] = subj
            singles[subj] -= 1
            used_today.add(subj)
    return all(v <= 0 for v in singles.values())

def schedule_class(subject_df: pd.DataFrame, days: int, periods_per_day: int):
    """Return timetable as list of lists."""
    tt = [["" for _ in range(periods_per_day)] for _ in range(days)]
    singles, blocks = build_requirements(subject_df)
    total_required = sum(singles.values()) + sum(bl for _, bl in blocks)
    capacity = days * periods_per_day
    if total_required > capacity:
        return False, tt, f"Required {total_required} periods but only {capacity} slots available."

    if not place_blocks(tt, blocks, days, periods_per_day):
        return False, tt, "Could not place all long sessions."

    if not fill_singles(tt, singles, days, periods_per_day):
        remaining = {k: v for k, v in singles.items() if v > 0}
        return False, tt, f"Couldn't allocate all sessions. Remaining: {remaining}"

    return True, tt, "Timetable generated."

# ------------------------- APP UI -------------------------
st.title("Automatic Timetable Generator")

with st.sidebar:
    st.header("Global Settings")
    days = st.number_input("Number of working days per week", min_value=1, max_value=7, value=5, step=1)
    periods_per_day = st.number_input("Periods per day", min_value=1, max_value=12, value=7, step=1)
    start_time = st.time_input("College start time", value=time(9, 0))
    period_minutes = st.number_input("Duration per period (minutes)", min_value=10, max_value=180, value=50, step=5)
    time_labels = time_slots(start_time, period_minutes, periods_per_day)

st.subheader("Classes & Subjects")
num_classes = st.number_input("Number of classes/sections", min_value=1, max_value=20, value=2, step=1)

class_configs = []
for idx in range(int(num_classes)):
    with st.expander(f"Class #{idx + 1} configuration", expanded=(idx == 0)):
        class_name = st.text_input(f"Class name #{idx + 1}", value=chr(65 + idx))
        st.caption("Use 'Is_Long_Session' and 'Session_Length' for labs/projects. Use 'Periods_per_Week' for all subjects.")
        editable_df = st.data_editor(
            seed_subject_rows(),
            num_rows="dynamic",
            use_container_width=True,
            column_config={
                "Type": st.column_config.SelectboxColumn(options=["Theory", "Lab/Project"]),
                "Is_Long_Session": st.column_config.CheckboxColumn(),
                "Session_Length": st.column_config.NumberColumn(min_value=1, max_value=6, step=1),
                "Periods_per_Week": st.column_config.NumberColumn(min_value=0, max_value=30, step=1),
            },
            key=f"editor_{idx}",
        )
        class_configs.append((class_name.strip() or f"Class_{idx+1}", sanitize_subjects(editable_df)))

st.divider()

col_left, col_right = st.columns([1, 1])
with col_left:
    generate = st.button("Generate Timetables")
with col_right:
    randomize_seed = st.checkbox("Randomize placement (shuffle)", value=True)

if generate:
    if randomize_seed:
        random.seed()

    all_tables = {}
    any_error = False
    errors = []

    for class_name, subj_df in class_configs:
        ok, grid, msg = schedule_class(subj_df, int(days), int(periods_per_day))
        if not ok:
            any_error = True
            errors.append(f"[{class_name}] {msg}")
        df = pd.DataFrame(grid, columns=[f"P{p+1}\n{time_labels[p]}" for p in range(periods_per_day)])
        df.insert(0, "Day", [f"Day {i+1}" for i in range(days)])
        all_tables[class_name] = df

    if any_error:
        st.error("Some timetables could not be generated due to constraints:")
        for e in errors:
            st.write("• " + e)

    st.subheader("Preview in Browser")
    for cname, df in all_tables.items():
        st.markdown(f"**{cname}**")
        st.dataframe(df, use_container_width=True)

    if all_tables:
        output = BytesIO()
        with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
            for cname, df in all_tables.items():
                safe_name = cname if len(cname) <= 31 else cname[:28] + "..."
                df.to_excel(writer, index=False, sheet_name=safe_name)
            cover = pd.DataFrame({
                "Info": [
                    "Automatic Timetable Generator",
                    f"Days per week: {days}",
                    f"Periods per day: {periods_per_day}",
                    f"Start time: {start_time.strftime('%H:%M')}",
                    f"Period duration: {period_minutes} minutes",
                ]
            })
            cover.to_excel(writer, index=False, sheet_name="Summary")
        st.download_button(
            label="Download Excel Workbook",
            data=output.getvalue(),
            file_name="timetables.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
