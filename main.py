from fastapi import FastAPI, File, UploadFile, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
import pandas as pd
import io
import json

app = FastAPI()

# Allow the HTML frontend to call this API from any origin
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── serve the frontend ────────────────────────────────────────────────────────

@app.get("/")
def serve_frontend():
    return FileResponse("index.html")

# ── helpers ────────────────────────────────────────────────────────────────────

def load_report(file_bytes: bytes) -> pd.DataFrame:
    report = pd.read_excel(io.BytesIO(file_bytes), skiprows=4)
    report.columns = report.iloc[0]
    report = report.drop(0).reset_index(drop=True)
    return report


def get_active(report: pd.DataFrame, user: str) -> pd.DataFrame:
    user_df = report[report["Imię i Nazwisko"] == user]
    return user_df[user_df["Status"] == "ACTIVE"]


# ── metric functions (mirror your original logic) ──────────────────────────────

def all_pubs(active: pd.DataFrame) -> int:
    return int(active["Liczba publikacji"].sum())

def avg_pubs(active: pd.DataFrame) -> float:
    return round(float(active["Liczba publikacji"].mean()), 2)

def publication_rate_1(active: pd.DataFrame) -> float:
    pct = (len(active[active["Liczba publikacji"] > 0]) / len(active)) * 100
    return round(pct, 2)

def publication_rate_3(active: pd.DataFrame) -> float:
    pct = (len(active[active["Liczba publikacji"] >= 3]) / len(active)) * 100
    return round(pct, 2)

def publication_rate_0(active: pd.DataFrame) -> float:
    pct = (len(active[active["Liczba publikacji"] == 0]) / len(active)) * 100
    return round(pct, 2)

def zeropubs(active: pd.DataFrame) -> int:
    return int(active[active["Liczba publikacji"] == 0].shape[0])

def zero_pubs_ids(active: pd.DataFrame) -> list:
    return active[active["Liczba publikacji"] == 0]["ID Treści"].tolist()

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
    """Return the list of unique user names in the uploaded file."""
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
    user: str = Form(...),
    metrics: str = Form(...),   # JSON-encoded list of selected metric keys
):
    """Run the selected metrics for the chosen user and return results."""
    contents = await file.read()
    selected = json.loads(metrics)

    try:
        report = load_report(contents)
        active = get_active(report, user)

        if active.empty:
            return JSONResponse(
                status_code=400,
                content={"error": f"No active records found for '{user}'"},
            )

        METRIC_MAP = {
            "all_pubs":           ("Total publications",          lambda: all_pubs(active)),
            "avg_pubs":           ("Avg publications per content", lambda: avg_pubs(active)),
            "rate_at_least_1":    ("% content with ≥1 pub",       lambda: f"{publication_rate_1(active)}%"),
            "rate_at_least_3":    ("% content with ≥3 pubs",      lambda: f"{publication_rate_3(active)}%"),
            "rate_zero":          ("% content with 0 pubs",        lambda: f"{publication_rate_0(active)}%"),
            "count_zero":         ("# content pieces with 0 pubs", lambda: zeropubs(active)),
            "ids_zero":           ("Content IDs with 0 pubs",      lambda: zero_pubs_ids(active)),
            "top3_reach":         ("Top 3 content by reach",        lambda: top3_by_reach(active)),
        }

        results = {}
        for key in selected:
            if key in METRIC_MAP:
                label, fn = METRIC_MAP[key]
                results[label] = fn()

        return {"user": user, "results": results}

    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
