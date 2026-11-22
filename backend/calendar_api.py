"""Read and update the shared orchard Calendar collection in MongoDB."""

from __future__ import annotations

import calendar as py_calendar
from datetime import datetime, timezone

from bson import ObjectId
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from pymongo.database import Database

_UTC = timezone.utc


class CreateTaskRequest(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    suggestionId: str | None = None
    year: int = 2026


class UpdateTaskRequest(BaseModel):
    completed: bool | None = None
    text: str | None = Field(default=None, min_length=1, max_length=500)
    year: int = 2026


class CreateNoteRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    year: int = 2026


def _iso_utc(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=_UTC)
    return value.astimezone(_UTC).isoformat().replace("+00:00", "Z")


def _available_years(db: Database) -> list[int]:
    years = sorted(
        int(doc["year"])
        for doc in db["Calendar"].find({"year": {"$exists": True}}, {"year": 1})
        if isinstance(doc.get("year"), int)
    )
    return years


def _serialize_calendar(doc: dict, available_years: list[int] | None = None) -> dict:
    months = []
    for month in sorted(doc.get("months") or [], key=lambda m: m.get("monthIndex", 0)):
        days = []
        for entry in sorted(month.get("days") or [], key=lambda d: d.get("day", 0)):
            tasks = [
                {
                    "id": str(task["id"]),
                    "text": task["text"],
                    "completed": bool(task.get("completed", False)),
                    "suggestionId": str(task["suggestionId"]) if task.get("suggestionId") else None,
                }
                for task in entry.get("tasks") or []
            ]
            notes = [
                {
                    "id": str(note["id"]),
                    "text": note["text"],
                    "createdAt": _iso_utc(note.get("createdAt")),
                }
                for note in entry.get("notes") or []
            ]
            days.append(
                {
                    "day": int(entry["day"]),
                    "date": entry.get("date")
                    or f"{int(doc.get('year', 2026)):04d}-{int(month['monthIndex']) + 1:02d}-{int(entry['day']):02d}",
                    "tasks": tasks,
                    "notes": notes,
                }
            )
        months.append(
            {
                "monthIndex": int(month["monthIndex"]),
                "name": month["name"],
                "suggestions": [
                    {
                        "id": str(item["id"]),
                        "text": item["text"],
                        "textEn": item.get("textEn") or item["text"],
                    }
                    for item in month.get("suggestions") or []
                ],
                "development": [
                    {
                        "id": str(item["id"]),
                        "text": item["text"],
                        "textEn": item.get("textEn") or item["text"],
                        "startDate": item["startDate"],
                        "endDate": item["endDate"],
                    }
                    for item in month.get("development") or []
                ],
                "days": days,
            }
        )
    year_val = int(doc.get("year", 2026))
    return {
        "id": str(doc["_id"]),
        "year": year_val,
        "availableYears": available_years if available_years else [year_val],
        "months": months,
        "updatedAt": _iso_utc(doc.get("updatedAt")),
    }


def _find_calendar(db: Database, year: int | None) -> dict:
    if year is not None:
        doc = db["Calendar"].find_one({"year": year})
    else:
        current_year = datetime.now(_UTC).year
        doc = db["Calendar"].find_one({"year": current_year}) or db["Calendar"].find_one(
            {}, sort=[("year", 1)]
        )
    if doc is None:
        raise HTTPException(status_code=404, detail="Calendar document not found")
    return doc


def _validate_month_day(year: int, month_index: int, day: int) -> str:
    if not 0 <= month_index <= 11:
        raise HTTPException(status_code=400, detail="month_index must be between 0 and 11")
    max_day = py_calendar.monthrange(year, month_index + 1)[1]
    if not 1 <= day <= max_day:
        raise HTTPException(
            status_code=400,
            detail=f"day must be between 1 and {max_day} for {year}-{month_index + 1:02d}",
        )
    return f"{year:04d}-{month_index + 1:02d}-{day:02d}"


def _get_or_create_day(month: dict, day: int, date_iso: str) -> dict:
    days = month.setdefault("days", [])
    for entry in days:
        if int(entry["day"]) == day:
            entry.setdefault("tasks", [])
            entry.setdefault("notes", [])
            return entry
    entry = {"day": day, "date": date_iso, "tasks": [], "notes": []}
    days.append(entry)
    days.sort(key=lambda item: int(item["day"]))
    return entry


def _prune_empty_day(month: dict, day: int) -> None:
    month["days"] = [
        entry
        for entry in month.get("days") or []
        if int(entry["day"]) != day or entry.get("tasks") or entry.get("notes")
    ]


def _save_months(db: Database, doc: dict) -> dict:
    now = datetime.now(_UTC)
    db["Calendar"].update_one(
        {"_id": doc["_id"]},
        {"$set": {"months": doc["months"], "updatedAt": now}},
    )
    doc["updatedAt"] = now
    return _serialize_calendar(doc, _available_years(db))


def create_calendar_router(db: Database) -> APIRouter:
    router = APIRouter(prefix="/api/v1/calendar", tags=["calendar"])

    @router.get("")
    def get_calendar(year: int | None = Query(default=None)) -> dict:
        return _serialize_calendar(_find_calendar(db, year), _available_years(db))

    @router.post("/months/{month_index}/days/{day}/tasks", status_code=201)
    def add_day_task(month_index: int, day: int, body: CreateTaskRequest) -> dict:
        text = body.text.strip()
        if not text:
            raise HTTPException(status_code=422, detail="Task text cannot be empty")

        suggestion_oid: ObjectId | None = None
        if body.suggestionId:
            if not ObjectId.is_valid(body.suggestionId):
                raise HTTPException(status_code=400, detail="suggestionId must be a valid ObjectId")
            suggestion_oid = ObjectId(body.suggestionId)

        doc = _find_calendar(db, body.year)
        year = int(doc.get("year", body.year))
        date_iso = _validate_month_day(year, month_index, day)
        month = doc["months"][month_index]
        day_entry = _get_or_create_day(month, day, date_iso)
        day_entry["tasks"].append(
            {
                "id": ObjectId(),
                "text": text,
                "completed": False,
                "suggestionId": suggestion_oid,
            }
        )
        return _save_months(db, doc)

    @router.patch("/months/{month_index}/days/{day}/tasks/{task_id}")
    def update_day_task(
        month_index: int, day: int, task_id: str, body: UpdateTaskRequest
    ) -> dict:
        if not ObjectId.is_valid(task_id):
            raise HTTPException(status_code=400, detail="task_id must be a valid ObjectId")

        doc = _find_calendar(db, body.year)
        year = int(doc.get("year", body.year))
        _validate_month_day(year, month_index, day)
        month = doc["months"][month_index]

        target_oid = ObjectId(task_id)
        for entry in month.get("days") or []:
            if int(entry["day"]) != day:
                continue
            for task in entry.get("tasks") or []:
                if task.get("id") == target_oid:
                    if body.completed is not None:
                        task["completed"] = bool(body.completed)
                    if body.text is not None:
                        cleaned = body.text.strip()
                        if not cleaned:
                            raise HTTPException(status_code=422, detail="Task text cannot be empty")
                        task["text"] = cleaned
                    return _save_months(db, doc)

        raise HTTPException(status_code=404, detail="Task not found")

    @router.delete("/months/{month_index}/days/{day}/tasks/{task_id}")
    def delete_day_task(
        month_index: int,
        day: int,
        task_id: str,
        year: int = Query(default=2026),
    ) -> dict:
        if not ObjectId.is_valid(task_id):
            raise HTTPException(status_code=400, detail="task_id must be a valid ObjectId")

        doc = _find_calendar(db, year)
        doc_year = int(doc.get("year", year))
        _validate_month_day(doc_year, month_index, day)
        month = doc["months"][month_index]

        target_oid = ObjectId(task_id)
        removed = False
        for entry in month.get("days") or []:
            if int(entry["day"]) != day:
                continue
            before = len(entry.get("tasks") or [])
            entry["tasks"] = [t for t in entry.get("tasks") or [] if t.get("id") != target_oid]
            if len(entry["tasks"]) != before:
                removed = True
                break

        if not removed:
            raise HTTPException(status_code=404, detail="Task not found")

        _prune_empty_day(month, day)
        return _save_months(db, doc)

    @router.post("/months/{month_index}/days/{day}/notes", status_code=201)
    def add_day_note(month_index: int, day: int, body: CreateNoteRequest) -> dict:
        text = body.text.strip()
        if not text:
            raise HTTPException(status_code=422, detail="Note text cannot be empty")

        doc = _find_calendar(db, body.year)
        year = int(doc.get("year", body.year))
        date_iso = _validate_month_day(year, month_index, day)
        month = doc["months"][month_index]
        day_entry = _get_or_create_day(month, day, date_iso)
        day_entry["notes"].append(
            {
                "id": ObjectId(),
                "text": text,
                "createdAt": datetime.now(_UTC),
            }
        )
        return _save_months(db, doc)

    @router.delete("/months/{month_index}/days/{day}/notes/{note_id}")
    def delete_day_note(
        month_index: int,
        day: int,
        note_id: str,
        year: int = Query(default=2026),
    ) -> dict:
        if not ObjectId.is_valid(note_id):
            raise HTTPException(status_code=400, detail="note_id must be a valid ObjectId")

        doc = _find_calendar(db, year)
        doc_year = int(doc.get("year", year))
        _validate_month_day(doc_year, month_index, day)
        month = doc["months"][month_index]

        target_oid = ObjectId(note_id)
        removed = False
        for entry in month.get("days") or []:
            if int(entry["day"]) != day:
                continue
            before = len(entry.get("notes") or [])
            entry["notes"] = [n for n in entry.get("notes") or [] if n.get("id") != target_oid]
            if len(entry["notes"]) != before:
                removed = True
                break

        if not removed:
            raise HTTPException(status_code=404, detail="Note not found")

        _prune_empty_day(month, day)
        return _save_months(db, doc)

    return router
