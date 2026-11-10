import datetime
from typing import List, Optional
import jwt
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel, ConfigDict
from ldap3 import Server, Connection, ALL, SIMPLE, IP_V4_ONLY

from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import (create_async_engine,
                                    async_sessionmaker,
                                    AsyncSession)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.orm import joinedload
from sqlalchemy import ForeignKey, select, or_, and_, func



# ==================== НАСТРОЙКИ LDAP И JWT ====================
# Укажите данные вашего LDAP / Active Directory сервера
LDAP_SERVER = "ldap://hnpz-dc-03" 

LDAP_DOMAIN = "ipc-oil.ru"  # Например, 'company.com'
# Шаблон для авторизации: user@domain.local
LDAP_USER_DN_TEMPLATE = "aleksandr.skabelkin@" + LDAP_DOMAIN 
LDAP_SEARCH_BASE = "OU=IT,OU=Users,OU=HNPZ,OU=DZO,OU=OUs,DC=ipc-oil,DC=ru" 
ALLOWED_GROUP_DN = "CN=HNPZ-UITIM-ASUTP-W,OU=Groups,DC=IPC-OIL,DC=ru"
JWT_SECRET_KEY = "7c2ee9233c1835968fab0a5e6d4044b68ede88f80223ad648fd78443fd2385ef"  # Поменяйте в продакшене!
JWT_ALGORITHM = "HS256"
JWT_ACCESS_TOKEN_EXPIRE_MINUTES = 480  # Токен на 8 часов (рабочий день)

# fastapi инструмент для извлечения токена из заголовка Authorization: Bearer <TOKEN>
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")

# ==================== СХЕМЫ ДЛЯ АВТОРИЗАЦИИ ====================
class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    username: str

# Добавьте в существующий код базы данных и Pydantic...
# (Код моделей ObjectModel, TaskModel и схем TaskResponse остается без изменений)



# 1. Настройка базы данных SQLite (Асинхронный режим)
DATABASE_URL = "sqlite+aiosqlite:///./database.db"
engine = create_async_engine(DATABASE_URL, connect_args={"check_same_thread": False})
async_session = async_sessionmaker(engine, expire_on_commit=False)

# Зависимость для получения сессии БД в эндпоинтах
async def get_db():
    async with async_session() as session:
        yield session

# 2. Модели SQLAlchemy (База данных)
class Base(DeclarativeBase):
    pass

class ObjectModel(Base):
    __tablename__ = "objects"
    
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(unique=True, index=True)
    
    tasks: Mapped[List["TaskModel"]] = relationship(back_populates="object_rel")

class TaskModel(Base):
    __tablename__ = "tasks"
    
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    date: Mapped[datetime.date] = mapped_column(default=datetime.date.today)
    object_id: Mapped[int] = mapped_column(ForeignKey("objects.id"))
    what_said: Mapped[Optional[str]] = mapped_column()
    what_was: Mapped[Optional[str]] = mapped_column()
    what_done: Mapped[Optional[str]] = mapped_column()
    status: Mapped[str] = mapped_column(default="В работе")
    who: Mapped[Optional[str]] = mapped_column()
    note: Mapped[Optional[str]] = mapped_column()

    object_rel: Mapped["ObjectModel"] = relationship(back_populates="tasks")

# 3. Схемы Pydantic (Валидация данных для фронтенда)
class ObjectBase(BaseModel):
    name: str

class ObjectResponse(ObjectBase):
    id: int
    model_config = ConfigDict(from_attributes=True)

class TaskBase(BaseModel):
    date: datetime.date
    object_id: int
    what_said: Optional[str] = None
    what_was: Optional[str] = None
    what_done: Optional[str] = None
    status: str = "В работе"
    who: Optional[str] = None
    note: Optional[str] = None

class TaskCreate(TaskBase):
    pass

class TaskUpdate(BaseModel):
    date: Optional[datetime.date] = None
    object_id: Optional[int] = None
    what_said: Optional[str] = None
    what_was: Optional[str] = None
    what_done: Optional[str] = None
    status: Optional[str] = None
    who: Optional[str] = None
    note: Optional[str] = None

class TaskResponse(TaskBase):
    id: int
    object_name: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)

class PaginatedTaskResponse(BaseModel):
    total: int
    limit: int
    offset: int
    results: List[TaskResponse]

# 4. Инициализация FastAPI и CORS
app = FastAPI(title="Task & Object Management API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==================== ФУНКЦИИ СЛУЖБЫ БЕЗОПАСНОСТИ ====================

def authenticate_via_ldap(username: str, password: str) -> bool:
    """Проверка логина и пароля на сервере LDAP (Active Directory)"""
    if not username or not password:
        return False
        
    user_dn = LDAP_USER_DN_TEMPLATE.format(username=username)
    try:
        # Подключаемся к серверу
        server = Server(LDAP_SERVER, get_info=None, connect_timeout=5, mode=IP_V4_ONLY)
        # Пытаемся выполнить Bind (авторизоваться)
        with Connection(server, user=user_dn, password=password, authentication=SIMPLE, auto_referrals=False) as conn:
            if conn.bind():
                # --- ШАГ ПОИСКА АТРИБУТА ---
                # Ищем пользователя по его системному имени (sAMAccountName)
                search_filter = (f"(sAMAccountName={username})"
                                 #f"(memberOf:1.2.840.113556.1.4.1941:={ALLOWED_GROUP_DN}))"
                                 )
                # Запрашиваем атрибут displayName (можно добавить 'mail', если нужна почта)
                conn.search(
                    search_base=LDAP_SEARCH_BASE,
                    search_filter=search_filter,
                    #search_scope=SUBTREE,
                    attributes=['displayName']
                )
                
                if conn.entries:
                    # Вытаскиваем значение displayName из первой найденной записи
                    entry = conn.entries[0]
                    if hasattr(entry, 'displayName') and entry.displayName.value:
                        return str(entry.displayName.value)
                
                # Если displayName почему-то пустой, возвращаем исходный логин
                    return username
                else:
                    # Если пароль верный, но пользователя нет в этом OU или он не в группе:
                    print(f"Доступ отклонен: {username} отсутствует в разрешенном OU или группе.")
                    return None
    except Exception as e:
        print(f"LDAP Error: {e}")
        return False
    return False

def create_access_token(username: str) -> str:
    """Генерация JWT токена"""
    expire = datetime.datetime.utcnow() + datetime.timedelta(minutes=JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode = {"sub": username, "exp": expire}
    encoded_jwt = jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
    return encoded_jwt

async def get_current_user(token: str = Depends(oauth2_scheme)) -> str:
    """Зависимость для проверки JWT токена в защищенных эндпоинтах"""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Не удалось валидировать учетные данные",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
        return username
    except jwt.PyJWTError:
        raise credentials_exception

# ==================== ЭНДПОИНТ АВТОРИЗАЦИИ ====================

@app.post("/auth/login", response_model=TokenResponse, tags=["Auth"])
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    # Теперь функция возвращает строку с ФИО или None
    display_name = authenticate_via_ldap(form_data.username, form_data.password)
    
    if not display_name:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный логин или пароль корпоративной сети"
        )
        
    # В JWT-токен (sub) по-прежнему лучше зашивать уникальный логин (username),
    # чтобы по нему бэкенд однозначно идентифицировал пользователя при защищенных запросах.
    access_token = create_access_token(username=form_data.username)
    
    return {
        "access_token": access_token, 
        "token_type": "bearer",
        "username": display_name  # 👈 Отдаем на фронтенд красивое ФИО вместо логина!
    }



@app.on_event("startup")
async def startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

# ==================== ЭНДПОИНТЫ ДЛЯ ОБЪЕКТОВ ====================

@app.get("/objects/", response_model=List[ObjectResponse], tags=["Objects"])
async def get_objects(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ObjectModel))
    return result.scalars().all()

@app.post("/objects/", response_model=ObjectResponse, tags=["Objects"])
async def create_object(obj: ObjectBase, db: AsyncSession = Depends(get_db), current_user: str = Depends(get_current_user)):
    db_obj = ObjectModel(name=obj.name.strip())
    db.add(db_obj)
    try:
        await db.commit()
        await db.refresh(db_obj)
        return db_obj
    except Exception:
        await db.rollback()
        raise HTTPException(status_code=400, detail="Объект с таким именем уже существует")

# ==================== ЭНДПОИНТЫ ДЛЯ ТАБЛИЦЫ ЗАДАЧ ====================
@app.get("/tasks/", response_model=PaginatedTaskResponse, tags=["Tasks"])
async def get_tasks(
    objectFilter: Optional[int] = None,
    statusFilter: Optional[str] = None,
    dateFilter: Optional[datetime.date] = None,
    monthFilter: Optional[str] = None,  # 👈 Добавляем новый параметр фильтрации в формате "YYYY-MM"
    search: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    current_user: str = Depends(get_current_user)
):
    query = select(TaskModel).options(joinedload(TaskModel.object_rel)).join(TaskModel.object_rel)
    filters = []
    
    if objectFilter is not None:
        filters.append(TaskModel.object_id == objectFilter)
        
    if statusFilter is not None:
        filters.append(TaskModel.status == statusFilter)
        
    if dateFilter is not None:
        filters.append(TaskModel.date == dateFilter)

    # Фильтр по выбранному месяцу (например, "2026-11")
    if monthFilter and not dateFilter:
        try:
            year, month = map(int, monthFilter.split("-"))
            start_date = datetime.date(year, month, 1)
            if month == 12:
                end_date = datetime.date(year + 1, 1, 1) - datetime.timedelta(days=1)
            else:
                end_date = datetime.date(year, month + 1, 1) - datetime.timedelta(days=1)
            filters.append(TaskModel.date.between(start_date, end_date))
        except ValueError:
            pass
        
    if search:
        search_filter = f"%{search}%"
        filters.append(
            or_(
                TaskModel.what_said.ilike(search_filter),
                TaskModel.what_was.ilike(search_filter),
                TaskModel.what_done.ilike(search_filter),
                TaskModel.who.ilike(search_filter),
                TaskModel.note.ilike(search_filter),
                ObjectModel.name.ilike(search_filter)
            )
        )
        
    if filters:
        query = query.where(and_(*filters))
        
    count_query = select(func.count(TaskModel.id)).join(TaskModel.object_rel)
    if filters:
        count_query = count_query.where(and_(*filters))
            
    total_result = await db.execute(count_query)
    total = total_result.scalar_one()
    
    # Если запрашивается календарный вид (передан monthFilter), отключаем лимит пагинации
    if monthFilter:
        query = query.order_by(TaskModel.id.desc())
    else:
        query = query.order_by(TaskModel.id.desc()).limit(limit).offset(offset)
    
    result = await db.execute(query)
    tasks = result.scalars().all()
    
    task_list = []
    for task in tasks:
        task_data = TaskResponse.model_validate(task)
        task_data.object_name = task.object_rel.name if task.object_rel else "Неизвестный объект"
        task_list.append(task_data)
        
    return PaginatedTaskResponse(
        total=total,
        limit=limit,
        offset=offset,
        results=task_list
    )



@app.post("/tasks/", response_model=TaskResponse, status_code=status.HTTP_201_CREATED, tags=["Tasks"])
async def create_task(
    task: TaskCreate, 
    db: AsyncSession = Depends(get_db),
    current_user: str = Depends(get_current_user)):  # 👈 ТЕПЕРЬ ТРЕБУЕТ ТОКЕН!):
    # Теперь внутри функции в переменной current_user лежит логин того, кто делает запрос
    # Вы можете записать его в поле `who`, если фронтенд его не прислал:
    task_data = task.model_dump()
    if not task_data.get("who"):
        task_data["who"] = current_user
    obj_query = select(ObjectModel).where(ObjectModel.id == task.object_id)
    obj_result = await db.execute(obj_query)
    associated_object = obj_result.scalar_one_or_none()
    
    if not associated_object:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail=f"Связанный объект с ID {task.object_id} не найден. Сначала создайте объект."
        )
        
    db_task = TaskModel(**task.model_dump())
    db.add(db_task)
    await db.commit()
    await db.refresh(db_task)
    
    response_data = TaskResponse.model_validate(db_task)
    response_data.object_name = associated_object.name
    
    return response_data

@app.put("/tasks/{task_id}", response_model=TaskResponse, tags=["Tasks"])
async def update_task(task_id: int, task_update: TaskUpdate, db: AsyncSession = Depends(get_db), current_user: str = Depends(get_current_user)):
    # Запрашиваем сразу с предзагрузкой объекта, чтобы избежать ленивой загрузки
    result = await db.execute(
        select(TaskModel).options(joinedload(TaskModel.object_rel)).where(TaskModel.id == task_id)
    )
    db_task = result.scalar_one_or_none()
    if not db_task:
        raise HTTPException(status_code=404, detail="Запись не найдена")
    
    update_data = task_update.model_dump(exclude_unset=True)
    if not update_data.get("who"):
        update_data["who"] = current_user
    if "object_id" in update_data:
        obj_check = await db.execute(select(ObjectModel).where(ObjectModel.id == update_data["object_id"]))
        associated_object = obj_check.scalar_one_or_none()
        if not associated_object:
            raise HTTPException(status_code=404, detail="Указанный Объект не найден")

    for key, value in update_data.items():
        setattr(db_task, key, value)
        
    try:
        await db.commit()
        # Перезапрашиваем данные из базы со связями, чтобы гарантировать актуальность object_name
        res = await db.execute(
            select(TaskModel).options(joinedload(TaskModel.object_rel)).where(TaskModel.id == task_id)
        )
        updated_task = res.scalar_one()
        
        response_data = TaskResponse.model_validate(updated_task)
        response_data.object_name = updated_task.object_rel.name if updated_task.object_rel else "Неизвестный объект"
        return response_data
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=f"Ошибка при обновлении задачи: {str(e)}")

@app.delete("/tasks/{task_id}", tags=["Tasks"])
async def delete_task(task_id: int, db: AsyncSession = Depends(get_db), current_user: str = Depends(get_current_user)):
    result = await db.execute(select(TaskModel).where(TaskModel.id == task_id))
    db_task = result.scalar_one_or_none()
    if not db_task:
        raise HTTPException(status_code=404, detail="Запись не найдена")
        
    await db.delete(db_task)
    await db.commit()
    return {"status": "success", "message": f"Запись №{task_id} успешно удалена"}

@app.put("/objects/{obj_id}", response_model=ObjectResponse, tags=["Objects"])
async def update_object(obj_id: int, obj_update: ObjectBase, db: AsyncSession = Depends(get_db), current_user: str = Depends(get_current_user)):
    result = await db.execute(select(ObjectModel).where(ObjectModel.id == obj_id))
    db_obj = result.scalar_one_or_none()
    
    if not db_obj:
        raise HTTPException(status_code=404, detail="Объект не найден")
    
    clean_name = obj_update.name.strip()
    name_check = await db.execute(select(ObjectModel).where(ObjectModel.name == clean_name, ObjectModel.id != obj_id))
    if name_check.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Объект с таким именем уже существует")
    db_obj.name = clean_name
    try:
        await db.commit()
        await db.refresh(db_obj)
        return db_obj
    except Exception:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Ошибка при обновлении объекта")

@app.delete("/objects/{obj_id}", tags=["Objects"])
async def delete_object(obj_id: int, db: AsyncSession = Depends(get_db), current_user: str = Depends(get_current_user)):
    result = await db.execute(select(ObjectModel).where(ObjectModel.id == obj_id))
    db_obj = result.scalar_one_or_none()
    if not db_obj:
        raise HTTPException(status_code=404, detail="Объект не найден")
    tasks_check = await db.execute(select(TaskModel).where(TaskModel.object_id == obj_id).limit(1))
    if tasks_check.scalar_one_or_none():
        raise HTTPException(
    status_code=400,
    detail="Нельзя удалить объект, так как к нему привязаны задачи в главной таблице. Сначала удалите или переназначьте задачи."
    )
    await db.delete(db_obj)
    await db.commit()
    return {"status": "success", "message": f"Объект '{db_obj.name}' успешно удален"}

