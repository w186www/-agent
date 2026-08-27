"""FastAPI 应用入口：组装路由层与全局异常处理，启动后访问 /docs 查看接口文档。"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .handlers import register_exception_handlers
from .log import get_logger
from .routers.assessment import router as assessment_router
from .routers.assessment_records import router as assessment_records_router
from .routers.auth import router as auth_router
from .routers.bidding_tasks import router as bidding_tasks_router
from .routers.chat_stream import router as chat_stream_router
from .routers.health import router as health_router
from .routers.kb import router as kb_router
from .routers.sessions import router as sessions_router
from .routers.upload import router as upload_router
from .routers.user import router as user_router
from .services.cleanup_service import start_cleanup_scheduler

logger = get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时创建招标文件存储目录、挂载过期资源清理调度（每日 03:00）。"""
    # download_tender 落盘目录：启动时自动创建（幂等）
    Path(settings.tender_dir).mkdir(parents=True, exist_ok=True)
    start_cleanup_scheduler()
    logger.info("应用启动完成：%s v%s", settings.app_name, settings.app_version)
    yield


app = FastAPI(
    title=settings.app_name,
    description="FastAPI 四层架构示例（路由层 / 校验层 / 业务层 / 数据库层），含统一错误处理",
    version=settings.app_version,
    lifespan=lifespan,
)

# CORS：开发环境允许前端跨域请求（生产环境应限制具体域名）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载健康检查、认证与用户 CRUD 路由
app.include_router(health_router)
app.include_router(auth_router)
app.include_router(user_router)
app.include_router(upload_router)
app.include_router(sessions_router)
app.include_router(kb_router)
app.include_router(bidding_tasks_router)
app.include_router(assessment_router)
app.include_router(assessment_records_router)
app.include_router(chat_stream_router)

# 注册全局异常处理器
register_exception_handlers(app)
