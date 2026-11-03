"""文章查询、归属权限、内容清理及事务处理，不依赖 HTTP。"""

from datetime import UTC, datetime
from uuid import UUID

import nh3
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from python_backend.modules.articles.models import Article
from python_backend.modules.articles.schemas import ArticleInput
from python_backend.modules.users.models import User


class ArticleNotFoundError(Exception):
    pass


class InvalidArticleError(Exception):
    pass


class ArticleConflictError(Exception):
    pass


TAGS = {
    "p",
    "br",
    "h2",
    "h3",
    "h4",
    "strong",
    "em",
    "s",
    "u",
    "ul",
    "ol",
    "li",
    "blockquote",
    "pre",
    "code",
    "a",
    "img",
    "hr",
}


def article_data(article: Article, session, full=False):
    author = session.get(User, article.user_id)
    data = {
        "id": article.id,
        "authorId": article.user_id,
        "authorName": author.name or author.username,
        "title": article.title,
        "summary": article.summary,
        "category": article.category,
        "tags": article.tags,
        "coverUrl": article.cover_url,
        "status": article.status,
        "version": article.version,
        "createdAt": article.created_at,
        "updatedAt": article.updated_at,
        "publishedAt": article.published_at,
    }
    if full:
        data["content"] = article.content
    return data


def management_conditions(user: User):
    if any(role.id == 1 for role in user.roles):
        return []
    return [Article.user_id == user.id]


def find_article(session, article_id: UUID, manage=False, user: User | None = None):
    conditions = management_conditions(user) if manage else []
    article = session.scalar(select(Article).where(Article.id == article_id, *conditions))
    if article is None or (not manage and article.status != "published"):
        raise ArticleNotFoundError("文章不存在")
    return article


def page_articles(session, page, limit, q, status, category, manage, user: User | None = None):
    conditions = management_conditions(user) if manage else [Article.status == "published"]
    if q:
        conditions.append(
            or_(
                Article.title.icontains(q, autoescape=True),
                Article.summary.icontains(q, autoescape=True),
            )
        )
    if category:
        conditions.append(Article.category == category)
    if manage and status:
        conditions.append(Article.status == status)
    total = session.scalar(select(func.count()).select_from(Article).where(*conditions))
    order = Article.updated_at if manage else Article.published_at
    articles = session.scalars(
        select(Article)
        .where(*conditions)
        .order_by(order.desc(), Article.id.desc())
        .offset((page - 1) * limit)
        .limit(limit)
    )
    return {
        "items": [article_data(a, session) for a in articles],
        "total": total,
        "page": page,
        "limit": limit,
    }


def clean_input(body: ArticleInput):
    content = nh3.clean(
        body.content,
        tags=TAGS,
        attributes={
            "a": {"href", "target"},
            "img": {"src", "alt", "title"},
            "code": {"class"},
            "ol": {"start"},
        },
        url_schemes={"http", "https", "mailto"},
        link_rel="noopener noreferrer",
    )
    plain = nh3.clean(content, tags=set()).strip()
    if body.status == "published" and not plain and "<img " not in content:
        raise InvalidArticleError("发布前请填写正文")
    return {
        **body.model_dump(exclude={"version"}),
        "content": content,
        "summary": body.summary or plain[:160],
        "tags": list(dict.fromkeys(body.tags)),
    }


def create_article(body: ArticleInput, session: Session, user: User):
    article = Article(
        user_id=user.id,
        **clean_input(body),
        published_at=datetime.now(UTC) if body.status == "published" else None,
    )
    session.add(article)
    session.commit()
    session.refresh(article)
    return article_data(article, session, True)


def update_article(article_id: UUID, body: ArticleInput, session: Session, user: User):
    article = find_article(session, article_id, True, user)
    if body.version is None:
        raise InvalidArticleError("文章版本无效，请重新加载")
    values = clean_input(body)
    published_at = (
        (article.published_at or datetime.now(UTC)) if body.status == "published" else None
    )
    result = session.execute(
        update(Article)
        .where(Article.id == article_id, Article.version == body.version)
        .values(
            **values,
            updated_at=datetime.now(UTC),
            published_at=published_at,
            version=Article.version + 1,
        )
    )
    if result.rowcount == 0:
        session.rollback()
        raise ArticleConflictError("文章已在其他页面修改，请重新加载后再编辑")
    session.commit()
    session.refresh(article)
    return article_data(article, session, True)


def delete_article(article_id: UUID, session: Session, user: User):
    session.delete(find_article(session, article_id, True, user))
    session.commit()
