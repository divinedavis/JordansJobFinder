from .db import get_db
from .models import SavedSearch, Subscription, User


def seed_demo_user() -> dict:
    db = get_db()
    user = db.query(User).filter(User.email == "demo@example.com").one_or_none()
    if not user:
        user = User(email="demo@example.com")
        db.add(user)
        db.commit()
        db.refresh(user)

    if not user.subscription:
        db.add(Subscription(user_id=user.id))
        db.commit()

    search = db.query(SavedSearch).filter(SavedSearch.user_id == user.id).one_or_none()
    if not search:
        db.add(
            SavedSearch(
                user_id=user.id,
                title_slug="technical-product-manager",
                experience_bucket="10+",
                city_1="New York, NY",
                city_2="Atlanta, GA",
                city_3="Miami, FL",
            )
        )
        db.commit()

    return {"email": user.email}
