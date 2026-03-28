from fastapi import FastAPI, File, UploadFile, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
import pandas as pd
import io
import json
import os

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── serve the frontend ─────────────────────────────────────────────────────────

@app.get("/")
def serve_frontend():
    return FileResponse(os.path.join(os.path.dirname(__file__), "index.html"))

# ── helpers ────────────────────────────────────────────────────────────────────

def load_report(file_bytes: bytes) -> pd.DataFrame:
    report = pd.read_excel(io.BytesIO(file_bytes), skiprows=4)
    report.columns = report.iloc[0]
    report = report.drop(0).reset_index(drop=True)
    return report

def get_active(report: pd.DataFrame, user: str) -> pd.DataFrame:
    user_df = report[report["Imię i Nazwisko"] == user]
    return user_df[user_df["Status"] == "ACTIVE"]

# ── metric functions ───────────────────────────────────────────────────────────

COL = "Liczba publikacji"   # column name in the Excel file

def all_pubs(active: pd.DataFrame) -> int:
    return int(active[COL].sum(min_count=0))

def avg_pubs(active: pd.DataFrame) -> float:
    return round(float(active[COL].mean()), 2)

def publication_rate_1(active: pd.DataFrame) -> float:
    pct = (active[COL].notna().sum() / len(active)) * 100
    return round(pct, 2)

def publication_rate_3(active: pd.DataFrame) -> float:
    pct = (len(active[active[COL] >= 3]) / len(active)) * 100
    return round(pct, 2)

def publication_rate_0(active: pd.DataFrame) -> float:
    pct = (active[COL].isna().sum() / len(active)) * 100
    return round(pct, 2)

def zeropubs(active: pd.DataFrame) -> int:
    return int(active[COL].isna().sum())

def zero_pubs_ids(active: pd.DataFrame) -> list:
    return active[active[COL].isna()]["ID Treści"].tolist()

def zero_summary(active: pd.DataFrame) -> dict:
    ids = active[active[COL].isna()]["ID Treści"].tolist()
    total = len(active)
    count = len(ids)
    pct = round((count / total) * 100, 2) if total else 0
    return {"count": count, "pct": f"{pct}%", "ids": ids}

def top3_by_reach(active: pd.DataFrame) -> list:
    top3 = (
        active[["ID Treści", "Zasięg"]]
        .sort_values("Zasięg", ascending=False)
        .head(3)
    )
    return top3.to_dict(orient="records")

# ── endpoints ──────────────────────────────────────────────────────────────────

@app.post("/users")
async def get_users(file: UploadFile = File(...)):
    contents = await file.read()
    try:
        report = load_report(contents)
        users = sorted(report["Imię i Nazwisko"].dropna().unique().tolist())
        return {"users": users}
    except Exception as e:
        return JSONResponse(status_code=400, content={"error": str(e)})


@app.post("/calculate")
async def calculate(
    file: UploadFile = File(...),
    users: str = Form(...),     # JSON-encoded list of selected user names
    metrics: str = Form(...),   # JSON-encoded list of selected metric keys
):
    contents = await file.read()
    selected_users   = json.loads(users)
    selected_metrics = json.loads(metrics)

    try:
        report = load_report(contents)
    except Exception as e:
        return JSONResponse(status_code=400, content={"error": f"Could not read file: {e}"})

    all_results = []

    for user in selected_users:
        try:
            active = get_active(report, user)

            if active.empty:
                all_results.append({"user": user, "error": "No active records found"})
                continue

            METRIC_MAP = {
                "all_pubs":        ("Total publications",           lambda a=active: all_pubs(a)),
                "avg_pubs":        ("Avg publications per content", lambda a=active: avg_pubs(a)),
                "rate_at_least_1": ("% content with ≥1 pub",        lambda a=active: f"{publication_rate_1(a)}%"),
                "rate_at_least_3": ("% content with ≥3 pubs",       lambda a=active: f"{publication_rate_3(a)}%"),
                "rate_zero":       ("% content with 0 pubs",         lambda a=active: f"{publication_rate_0(a)}%"),
                "count_zero":      ("Number of posts with 0 pubs",   lambda a=active: zeropubs(a)),
                "ids_zero":        ("Content IDs with 0 pubs",       lambda a=active: zero_pubs_ids(a)),
                "top3_reach":      ("Top 3 content by reach",         lambda a=active: top3_by_reach(a)),
            }

            results = {}
            for key in selected_metrics:
                if key in METRIC_MAP:
                    label, fn = METRIC_MAP[key]
                    results[label] = fn()

            all_results.append({"user": user, "results": results})

        except Exception as e:
            all_results.append({"user": user, "error": str(e)})

    return {"results": all_results}
