import re

from django.contrib import admin
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext as _
from model_utils import Choices
from phonenumber_field.modelfields import PhoneNumberField

from slack.models import SlackUser, SlackChannel

# User = get_user_model()
from users.models import User


class Member(models.Model):
    """Model for a club member.

    Each Member has a one-to-zero-or-one relationship with User. Additional
    profile information such as the member's school, class year, and club
    position are also stored.
    """

    POSITIONS = Choices(
        (0, "general_member", _("General Member")),
        (1, "secretary", _("Secretary")),
        (2, "treasurer", _("Treasurer")),
        (3, "president", _("President")),
        (4, "senior_advisor", _("Senior Advisor")),
    )
    SCHOOLS = Choices(
        (0, "college", _("Columbia College")),
        (1, "engineering", _("School of Engineering and Applied Science")),
        (2, "barnard", _("Barnard College")),
        (3, "general_studies", _("School of General Studies")),
        (4, "other", _("Other")),
    )
    CLASS_YEARS = Choices(
        (0, "freshman", _("Freshman")),
        (1, "sophomore", _("Sophomore")),
        (2, "junior", _("Junior")),
        (3, "senior", _("Senior")),
        (4, "masters", _("Masters")),
        (5, "doctorate", _("Doctorate")),
        (6, "alumni", _("Alumni")),
        (7, "other", _("Other")),
    )

    user = models.OneToOneField(
        User, related_name="member", on_delete=models.CASCADE, null=True
    )
    position = models.PositiveSmallIntegerField(
        choices=POSITIONS, default=POSITIONS.general_member, verbose_name="position"
    )
    school = models.PositiveSmallIntegerField(
        choices=SCHOOLS, null=True, blank=True, default=None, verbose_name="school"
    )
    class_year = models.PositiveSmallIntegerField(
        choices=CLASS_YEARS,
        null=True,
        blank=True,
        default=None,
        verbose_name="class year",
    )

    def __str__(self):
        return f"{self.user.get_full_name()}"  # noqa

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self.fetch_slack_user()

    def fetch_slack_user(self):
        """Fetch Slack user for member, creating one if necessary"""
        return SlackUser.objects.get_or_create(member=self)[0]


class Show(models.Model):
    """Model for a show.

    Each Show stores information pertaining to the show, such as the date,
    time, venue address, number of lions, point person, performers, etc.
    """

    PRIORITIES = Choices(
        (0, "full", _("Full")),
        (1, "normal", _("Normal")),
        (2, "urgent", _("Urgent")),
    )
    STATUSES = Choices(
        (0, "draft", _("Draft")),
        (1, "published", _("Published")),
        (2, "closed", _("Closed")),
    )
    PAYMENT_METHODS = Choices(
        (0, "cash", _("Cash")),
        (1, "venmo", _("Venmo")),
        (2, "paypal", _("PayPal")),
        (3, "check", _("Check")),
    )

    name = models.CharField(max_length=60, null=False, blank=False)
    date = models.DateField(null=True, blank=True, verbose_name="show date")
    time = models.TimeField(
        null=True,
        blank=True,
        editable=False,
        verbose_name="show time",
        help_text="time of the first round of the show, updated automatically",
    )
    address = models.CharField(
        max_length=80,
        blank=True,
        verbose_name="venue address",
        help_text=_("Venue name or room number if on campus"),
    )
    is_campus = models.BooleanField(default=False, verbose_name="on campus")
    is_out_of_city = models.BooleanField(default=False, verbose_name="out of city")
    lions = models.PositiveSmallIntegerField(
        null=True, blank=True, verbose_name="Number of lions"
    )
    point = models.ForeignKey(
        "Member",
        related_name="pointed_shows",
        related_query_name="pointed_show",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="point person",
    )
    performers = models.ManyToManyField(
        "Member",
        related_name="performed_shows",
        related_query_name="performed_show",
        through="Role",
    )
    contact = models.ForeignKey(
        "Contact",
        related_name="shows",
        related_query_name="show",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    pending = models.BooleanField(default=True)
    status = models.PositiveSmallIntegerField(choices=STATUSES, default=STATUSES.draft)
    priority = models.PositiveSmallIntegerField(
        choices=PRIORITIES, default=PRIORITIES.normal
    )
    notes = models.TextField(blank=True, verbose_name="notes")
    rate = models.DecimalField(blank=True, null=True, decimal_places=2, max_digits=10, verbose_name="rate")
    payment_method = models.PositiveSmallIntegerField(choices=PAYMENT_METHODS, default=PAYMENT_METHODS.cash, verbose_name="payment method")

    class Meta:
        ordering = ["date", "time"]

    def __str__(self):
        return self.name

    def __iter__(self):
        for field in self._meta.fields:
            field_name = str(field).split(".")[-1]
            yield field_name, getattr(self, field_name, None)

    def clean(self):
        if self.status > Show.STATUSES.draft and self.date is None:
            raise ValidationError(
                {"status": _("Cannot publish show until date is set.")}
            )

    def save(self, *args, **kwargs):
        old_instance = Show.objects.filter(pk=self.pk).first()
        updated_fields = [
            field
            for field in ["name", "date", "time", "address", "lions", "point"]
            if getattr(self, field) != getattr(old_instance, field, None)
        ]

        super().save(*args, **kwargs)
        if self.status > Show.STATUSES.draft:
            channel, created = self.fetch_slack_channel()
            if not channel.is_archived():
                if created:
                    channel.send_or_update_briefing()
                    channel.invite_performers()
                else:
                    if updated_fields:
                        channel.send_or_update_briefing()
                        channel.send_update_message(
                            [
                                self._meta.get_field(field).verbose_name.lower()
                                for field in updated_fields
                            ]
                        )
                        if "name" in updated_fields or "date" in updated_fields:
                            channel.update_name()

    def delete(self, *args, **kwargs):
        self.status = self.STATUSES.draft
        self.save()
        if self.has_slack_channel() and not self.channel.is_archived():
            self.channel.archive(rename=True)
        super().delete(*args, **kwargs)

    def fetch_slack_channel(self):
        """Fetches Slack channel, or creates one if necessary.

        Returns:
            A tuple containing the fetched or newly created SlackChannel
            instance and a boolean indicating if an instance was created.

        Raises:
            SlackBossException: If there was an error creating the channel.
        """

        return SlackChannel.objects.get_or_create(show=self)

    def default_channel_name(self) -> str:
        """Generates the default Slack channel name for the show.

        The default name uses the format mm-dd-show-name.

        Returns:
            The default Slack channel name for the show.

        Raises:
            ValueError: If necessary fields for the name are missing.
        """

        if self.name == "":
            raise ValueError(
                "Default channel name requires the name of the show to be set."
            )
        if self.date is None:
            raise ValueError(
                "Default channel name requires the date of the show to be set."
            )
        name = re.sub(r"[^\w\s]", "", self.name)
        date = self.date.strftime("%m-%d")
        return f"{date}-{name.replace(' ', '-').lower()}"

    @admin.display(description="Day of Week")
    def day_of_week(self):
        return self.date.strftime("%a").upper() if self.date else None

    @admin.display(description="Date", ordering="date")
    def formatted_date(self, fmt="%m/%d"):
        return self.date.strftime(fmt) if self.date else None

    @admin.display(description="Time", ordering="time")
    def formatted_time(self, fmt="%-I:%M %p"):
        return self.time.strftime(fmt) if self.time else None

    @admin.display(description="Performers")
    def performer_count(self):
        return self.performers.count()

    @admin.display(description="Slack", boolean=True)
    def is_slack_channel_active(self):
        return self.has_slack_channel() and not self.channel.is_archived()

    def has_slack_channel(self):
        return hasattr(self, "channel")

    def is_open(self):
        return self.STATUSES.draft < self.status < self.STATUSES.closed


class Round(models.Model):
    """Model for a round of a show.

    Each Round belongs to a show and stores the performance time of that
    round. Each Show may have one or more Rounds (or none, if TBD).
    """

    show = models.ForeignKey(
        "Show",
        related_name="rounds",
        related_query_name="round",
        on_delete=models.CASCADE,
    )
    time = models.TimeField(null=True, blank=True)

    class Meta:
        unique_together = [["show", "time"]]

    def __str__(self):
        return f"{self.show} at {self.time}"


class Role(models.Model):
    """Model for a performer's role at a show.

    Each Role contains information about what role a performer played at a
    show, e.g., lion, drum, cymbal, gong, etc.
    """

    ROLES = Choices(
        (0, "lion", _("Lion")),
        (1, "drum", _("Drum")),
        (2, "cymbal", _("Cymbal")),
        (3, "gong", _("Gong")),
        (4, "monk", _("Monk")),
        (5, "other", _("Other")),
    )

    show = models.ForeignKey("Show", on_delete=models.CASCADE)
    performer = models.ForeignKey("Member", on_delete=models.CASCADE)
    role = models.PositiveSmallIntegerField(
        choices=ROLES, null=True, blank=True, default=None, verbose_name="role type"
    )

    class Meta:
        unique_together = [["show", "performer"]]

    def __str__(self):
        return f"{self.show.name} ({self.performer.user.get_full_name()})"  # noqa

    def save(self, *args, **kwargs):
        created = self._state.adding
        super().save(*args, **kwargs)
        if created and hasattr(self.show, "channel"):
            slack_user = self.performer.fetch_slack_user()
            if slack_user is not None:
                self.show.channel.invite_users(slack_user)

    def delete(self, *args, **kwargs):
        super().delete(*args, **kwargs)
        if hasattr(self.show, "channel"):
            slack_user = self.performer.fetch_slack_user()
            if slack_user is not None:
                self.show.channel.remove_users(slack_user)


class Contact(models.Model):
    """Model for a client contact.

    Each Contact contains information about the client's name, phone, email, etc.
    """

    first_name = models.CharField(max_length=30, blank=True)
    last_name = models.CharField(max_length=30, blank=True)
    phone = PhoneNumberField(null=True, blank=True)
    email = models.EmailField(max_length=60, blank=True)

    def __str__(self):
        return f"{self.first_name} {self.last_name}"
