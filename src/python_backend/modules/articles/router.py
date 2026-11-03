"""文章 HTTP 路由：参数、认证依赖和业务异常转换。"""

from contextlib import contextmanager
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from python_backend.modules.articles import service
from python_backend.modules.articles.schemas import ArticleInput, ArticleQuery
from python_backend.modules.users.models import User
from python_backend.modules.users.router import SessionDependency, require_editor

router = APIRouter(prefix="/articles", tags=["articles"])
Editor = Annotated[User, Depends(require_editor)]


@contextmanager
def article_errors():
    try:
        yield
    except service.ArticleNotFoundError as error:
        raise HTTPException(404, str(error)) from error
    except service.InvalidArticleError as error:
        raise HTTPException(422, str(error)) from error
    except service.ArticleConflictError as error:
        raise HTTPException(409, str(error)) from error


@router.get("")
def list_articles(session: SessionDependency, query: Annotated[ArticleQuery, Query()]):
    return service.page_articles(session, **query.model_dump(), manage=False)


@router.get("/manage")
def manage_articles(
    session: SessionDependency, user: Editor, query: Annotated[ArticleQuery, Query()]
):
    return service.page_articles(session, **query.model_dump(), manage=True, user=user)


@router.get("/manage/{article_id}")
def edit_article(article_id: UUID, session: SessionDependency, user: Editor):
    with article_errors():
        article = service.find_article(session, article_id, True, user)
        return service.article_data(article, session, True)


@router.get("/{article_id}")
def get_article(article_id: UUID, session: SessionDependency):
    with article_errors():
        article = service.find_article(session, article_id)
        return service.article_data(article, session, True)


@router.post("")
def create_article(body: ArticleInput, session: SessionDependency, user: Editor):
    with article_errors():
        return service.create_article(body, session, user)


@router.patch("/{article_id}")
def update_article(article_id: UUID, body: ArticleInput, session: SessionDependency, user: Editor):
    with article_errors():
        return service.update_article(article_id, body, session, user)


@router.delete("/{article_id}", status_code=204)
def delete_article(article_id: UUID, session: SessionDependency, user: Editor):
    with article_errors():
        service.delete_article(article_id, session, user)
    return Response(status_code=204)
