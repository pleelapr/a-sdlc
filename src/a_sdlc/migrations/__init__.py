"""Packaged Alembic migration environment for a-sdlc.

Relocated from the repository-root ``alembic/`` directory so the migration
scripts ship inside the installed wheel and Docker image. This lets
``alembic upgrade head`` run at server startup (and ``a-sdlc db ...`` work)
regardless of deployment layout. See ``a_sdlc.core.alembic_config``.
"""
