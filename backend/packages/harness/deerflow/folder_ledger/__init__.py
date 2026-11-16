"""Folder ledger: which conversations created or edited folders in shared writable mounts.

``mounts`` maps tool paths to tracked folders, ``fs`` deletes one confined to
its mount; the tables are in ``deerflow.persistence.folder_ledger``, the
recorder is ``agents/middlewares/folder_ledger_middleware.py`` and the routes
are the Gateway's ``/api/folder-ledger``.
"""
