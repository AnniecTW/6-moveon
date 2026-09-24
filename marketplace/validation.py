"""Shared validation for ordinary model saves and Admin model forms.

QuerySet.update(), bulk_create(), bulk_update() and raw SQL bypass model
validation. Only database constraints protect those paths; relationship
writes must use validated instance saves.
"""

from django.db import models, router
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator


def validate_image_reference(value):
    """Allow HTTP(S) images and same-origin absolute paths, never script/file URLs."""
    if value.startswith("/") and not value.startswith("//"):
        if "\\" not in value and not any(character.isspace() or ord(character) < 32 for character in value):
            return
        raise ValidationError("Enter a valid image path.")
    URLValidator(schemes=["http", "https"])(value)


def database_for(instance):
    return instance._state.db or router.db_for_write(type(instance), instance=instance)


def participant_errors(buyer_id, seller_id, owner_id=None):
    errors = {}
    if buyer_id is not None and buyer_id == seller_id:
        errors["buyer"] = "Buyer and seller must be different users."
    if owner_id is not None:
        if seller_id is not None and seller_id != owner_id:
            errors["seller"] = "The seller must be the listing owner."
        if buyer_id == owner_id:
            errors["buyer"] = (
                "You cannot buy or start a buying conversation about your own listing."
            )
    return errors


class ValidatedSaveModel(models.Model):
    """Run model validation for instance saves, including partial updates."""

    class Meta:
        abstract = True

    def save(
        self, *, force_insert=False, force_update=False, using=None, update_fields=None
    ):
        using = using or database_for(self)
        deferred = self.get_deferred_fields()
        if (
            update_fields is None
            and deferred
            and not self._state.adding
            and not force_insert
            and using == self._state.db
        ):
            # Match Django's implicit partial write before validation loads deferred fields.
            loaded = {
                field.attname
                for field in self._meta.concrete_fields
                if not field.primary_key and not field.generated
            } - deferred
            if loaded:
                update_fields = loaded
        if update_fields is not None:
            update_fields = frozenset(update_fields)
            if not update_fields:
                return
        candidate = self
        if update_fields is not None and not self._state.adding:
            # Validate the persisted result, not unsaved fields excluded from this write.
            candidate = type(self)._base_manager.using(using).get(pk=self.pk)
            for field in self._meta.concrete_fields:
                if field.name in update_fields or field.attname in update_fields:
                    setattr(candidate, field.attname, getattr(self, field.attname))
        candidate._state.db = using
        candidate.full_clean()
        return super().save(
            force_insert=force_insert,
            force_update=force_update,
            using=using,
            update_fields=update_fields,
        )
