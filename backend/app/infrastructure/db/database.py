from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from backend.app.config import load_config
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import DateTime
import datetime as dt


# Конфигурация
config = load_config()

# Двигатель БД
engine = create_async_engine(
    url=(
        f"mysql+aiomysql://{config.database.user}:{config.database.password}"
        f"@{config.database.host}:{config.database.db_port}/{config.database.db_name}"
    ),
    pool_pre_ping=True,  # Проверять соединение перед использованием
    pool_recycle=300,    # Пересоздавать соединения каждые 300 секунд
)

# Фабрика сессий
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    """Базовый класс для всех моделей"""
    id: Mapped[int] = mapped_column(autoincrement=True, primary_key=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow, nullable=False)

    def to_dict(self) -> dict:
        """Конвертация объекта в словарь"""
        return {c.key: getattr(self, c.key) for c in self.__table__.columns}


async def get_async_session() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
