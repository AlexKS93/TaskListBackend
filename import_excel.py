import os
import asyncio
import datetime
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from main import TaskModel, ObjectModel, Base

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./database.db")

connect_args = {"check_same_thread": False} if "sqlite" in DATABASE_URL else {}
engine = create_async_engine(DATABASE_URL, connect_args=connect_args)
async_session = async_sessionmaker(engine, expire_on_commit=False)

async def import_from_excel(file_path: str):
    if not os.path.exists(file_path):
        print(f"❌ Ошибка: Файл '{file_path}' не найден!")
        return

    print(f"📂 Чтение файла {file_path}...")
    df = pd.read_excel(file_path).fillna("")

    async with async_session() as db:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        # 1. Загружаем существующие объекты из БД
        obj_res = await db.execute(select(ObjectModel))
        existing_objects = {obj.name.strip().lower(): obj.id for obj in obj_res.scalars().all()}

        # 2. Загружаем "отпечатки" существующих задач для проверки на дубликаты
        tasks_res = await db.execute(
            select(TaskModel.date, TaskModel.object_id, TaskModel.what_said, TaskModel.who)
        )
        existing_signatures = set()
        for t_date, t_obj_id, t_said, t_who in tasks_res.all():
            sig = (
                t_date,
                t_obj_id,
                (t_said or "").strip().lower(),
                (t_who or "").strip().lower()
            )
            existing_signatures.add(sig)

        added_tasks_count = 0
        skipped_duplicates_count = 0
        created_objects_count = 0

        for index, row in df.iterrows():
            row_num = index + 2
            
            # Обработка Объекта
            obj_name = str(row.get("Объект", "")).strip()
            if not obj_name:
                print(f"⚠️ Строка {row_num} пропущена: не указан 'Объект'.")
                continue

            obj_key = obj_name.lower()
            if obj_key in existing_objects:
                object_id = existing_objects[obj_key]
            else:
                new_obj = ObjectModel(name=obj_name)
                db.add(new_obj)
                await db.flush()
                object_id = new_obj.id
                existing_objects[obj_key] = object_id
                created_objects_count += 1
                print(f"➕ Создан новый объект в справочнике: '{obj_name}'")

            # Обработка Даты
            raw_date = row.get("Дата", "")
            try:
                if isinstance(raw_date, (datetime.datetime, pd.Timestamp)):
                    task_date = raw_date.date()
                elif str(raw_date).strip():
                    task_date = pd.to_datetime(str(raw_date).strip(), dayfirst=True).date()
                else:
                    task_date = datetime.date.today()
            except Exception:
                print(f"⚠️ Строка {row_num}: неверный формат даты '{raw_date}'. Установлена текущая дата.")
                task_date = datetime.date.today()

            what_said = str(row.get("Что сказали", "")).strip()
            what_was = str(row.get("Что было", "")).strip()
            what_done = str(row.get("Что сделано", "")).strip()
            note = str(row.get("Примечание", "")).strip()
            # Если поле "Что сказали" пустое, берем значение из "Что сделано"
            if not what_said:
                what_said = what_done
            # Обработка Статуса
            raw_status = str(row.get("Статус", "")).strip()
            valid_statuses = ["В работе", "Выполнено", "Запланировано"]
            status = raw_status if raw_status in valid_statuses else "В работе"

            # 👥 РАЗДЕЛЕНИЕ ИСПОЛНИТЕЛЕЙ ПО ";"
            raw_who = str(row.get("Исполнитель", "")).strip()
            executors = [w.strip() for w in raw_who.split(";") if w.strip()]
            
            # Если ячейка исполнителя пустая, создаем список с одной пустой строкой
            if not executors:
                executors = [""]

            # Создаем отдельную задачу для каждого исполнителя из списка
            for who in executors:
                current_sig = (task_date, object_id, what_said.lower(), who.lower())
                
                if current_sig in existing_signatures:
                    skipped_duplicates_count += 1
                    continue

                new_task = TaskModel(
                    date=task_date,
                    object_id=object_id,
                    what_said=what_said,
                    what_was=what_was,
                    what_done=what_done,
                    status=status,
                    who=who,
                    note=note
                )
                db.add(new_task)
                existing_signatures.add(current_sig)
                added_tasks_count += 1

        await db.commit()
        
        print("\n✅ ИМПОРТ ЗАВЕРШЕН!")
        print(f"🏭 Создано новых объектов: {created_objects_count}")
        print(f"📋 Загружено новых задач: {added_tasks_count}")
        print(f"⏭️ Пропущено дубликатов: {skipped_duplicates_count}")

if __name__ == "__main__":
    EXCEL_FILE = "import_tasks.xlsx"
    asyncio.run(import_from_excel(EXCEL_FILE))
