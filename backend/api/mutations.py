import graphene
from django.contrib.sessions.models import Session
from django.utils import timezone
from graphql_jwt.decorators import login_required

from show_manager.models import Show, Member, Role
from users.models import User
from .types import RoleType, UserType


class CreateUserMutation(graphene.Mutation):
    user = graphene.Field(UserType)

    class Arguments:
        first_name = graphene.String(required=True)
        last_name = graphene.String(required=True)
        email = graphene.String(required=True)
        password = graphene.String(required=True)
        phone = graphene.String()

    @staticmethod
    def mutate(root, info, first_name, last_name, email, password, phone=""):
        user_instance = User.objects.create(
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name,
            phone=phone,
        )
        return CreateUserMutation(user=user_instance)


class CreateRoleMutation(graphene.Mutation):
    role = graphene.Field(RoleType)

    class Arguments:
        show_id = graphene.ID(required=True)

    @staticmethod
    def mutate(root, info, show_id):
        role_instance = Role(
            show=Show.objects.get(pk=show_id),
            performer=Member.objects.get(pk=info.context.user.member.id),
        )
        role_instance.save()
        return CreateRoleMutation(role=role_instance)


class DeleteRoleMutation(graphene.Mutation):
    role = graphene.Field(RoleType)

    class Arguments:
        show_id = graphene.ID(required=True)

    @staticmethod
    def mutate(root, info, show_id):
        role_instance = Role.objects.get(
            show=Show.objects.get(pk=show_id),
            performer=Member.objects.get(pk=info.context.user.member.id),
        )
        role_instance.delete()
        return DeleteRoleMutation(role=role_instance)


class EditUserMutation(graphene.Mutation):
    user = graphene.Field(UserType)

    class Arguments:
        first_name = graphene.String()
        last_name = graphene.String()
        email = graphene.String()
        phone = graphene.String()
        school = graphene.String()
        class_year = graphene.String()

    @staticmethod
    @login_required
    def mutate(root, info, **kwargs):
        user_instance = User.objects.get(pk=info.context.user.pk)
        for key, value in kwargs.items():
            if hasattr(user_instance, key):
                setattr(user_instance, key, value)
            elif hasattr(user_instance.member, key):
                setattr(user_instance.member, key, value)
        user_instance.save()
        user_instance.member.save()
        return EditUserMutation(user=user_instance)


class LogoutUserMutation(graphene.Mutation):
    ok = graphene.Boolean()
    id = graphene.ID()

    @staticmethod
    @login_required
    def mutate(root, info, **kwargs):
        user_id = info.context.user.pk
        for session in Session.objects.filter(expire_date__gte=timezone.now()):
            if str(user_id) == session.get_decoded().get("_auth_user_id"):
                session.delete()
        return LogoutUserMutation(id=user_id, ok=True)
