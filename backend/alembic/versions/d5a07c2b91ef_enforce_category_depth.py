"""enforce category depth

Revision ID: d5a07c2b91ef
Revises: b48271ca3e5d
"""

from alembic import op

revision: str = "d5a07c2b91ef"
down_revision: str | None = "b48271ca3e5d"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION validate_category_depth() RETURNS trigger AS $$
        DECLARE
            parent_level integer;
            parent_parent uuid;
        BEGIN
            IF NEW.parent_id IS NOT NULL THEN
                SELECT level, parent_id INTO parent_level, parent_parent
                FROM categories WHERE id = NEW.parent_id;
                IF NOT FOUND OR parent_level <> 0 OR parent_parent IS NOT NULL THEN
                    RAISE EXCEPTION 'category parent must be a root category';
                END IF;
            END IF;
            IF (NEW.level <> 0 OR NEW.parent_id IS NOT NULL) AND EXISTS (
                SELECT 1 FROM categories WHERE parent_id = NEW.id AND id <> NEW.id
            ) THEN
                RAISE EXCEPTION 'category with children must remain a root category';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER trg_categories_depth
        AFTER INSERT OR UPDATE OF parent_id, level ON categories
        DEFERRABLE INITIALLY IMMEDIATE
        FOR EACH ROW EXECUTE FUNCTION validate_category_depth()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_categories_depth ON categories")
    op.execute("DROP FUNCTION IF EXISTS validate_category_depth()")
