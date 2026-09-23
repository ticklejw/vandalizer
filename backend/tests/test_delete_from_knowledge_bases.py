"""Deleting a document can also remove it from the knowledge bases built from it.

Support ticket: the delete dialog said the file was removed from its KBs, but
the KB kept its source (and chunks) and chat kept answering from it. A KB
source answers from its own ingested copy, so removal is an explicit option on
delete — and only for KBs the caller may manage; the rest are reported back.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.test_files_routes import _auth_cookies, _make_user


def _source(uuid, kb_uuid):
    s = MagicMock()
    s.uuid = uuid
    s.knowledge_base_uuid = kb_uuid
    return s


def _kb(uuid, title):
    kb = MagicMock()
    kb.uuid = uuid
    kb.title = title
    return kb


def _find_returning(items):
    q = MagicMock()
    q.to_list = AsyncMock(return_value=items)
    return q


class TestRemoveDocumentFromKnowledgeBases:
    @pytest.mark.asyncio
    async def test_removes_from_manageable_and_reports_viewable_as_kept(self):
        from app.services import knowledge_service as svc

        sources = [_source("s1", "kb-own"), _source("s2", "kb-own"), _source("s3", "kb-view"), _source("s4", "kb-hidden")]
        own, view_only = _kb("kb-own", "Mine"), _kb("kb-view", "Verified NSF")

        async def get_kb(uuid, user, *, manage=False, **_):
            if uuid == "kb-own":
                return own
            if uuid == "kb-view" and not manage:
                return view_only
            return None

        with patch.object(svc.KnowledgeBaseSource, "find", return_value=_find_returning(sources)), \
             patch("app.services.organization_service.get_user_org_ancestry", AsyncMock(return_value=[])), \
             patch.object(svc, "get_knowledge_base", side_effect=get_kb), \
             patch.object(svc, "remove_source", AsyncMock(return_value=True)) as remove:
            removed, kept = await svc.remove_document_from_knowledge_bases("doc-1", MagicMock())

        assert removed == [{"uuid": "kb-own", "title": "Mine"}]
        # The view-only KB is named; the invisible one is not.
        assert kept == [{"uuid": "kb-view", "title": "Verified NSF"}]
        assert [c.args for c in remove.await_args_list] == [(own, "s1"), (own, "s2")]

    @pytest.mark.asyncio
    async def test_one_failing_kb_does_not_stop_the_others(self):
        from app.services import knowledge_service as svc

        sources = [_source("s1", "kb-a"), _source("s2", "kb-b")]
        kbs = {"kb-a": _kb("kb-a", "A"), "kb-b": _kb("kb-b", "B")}

        async def remove(kb, source_uuid):
            if kb.uuid == "kb-a":
                raise RuntimeError("chroma down")
            return True

        with patch.object(svc.KnowledgeBaseSource, "find", return_value=_find_returning(sources)), \
             patch("app.services.organization_service.get_user_org_ancestry", AsyncMock(return_value=[])), \
             patch.object(svc, "get_knowledge_base", AsyncMock(side_effect=lambda uuid, *a, **k: kbs[uuid])), \
             patch.object(svc, "remove_source", side_effect=remove):
            removed, kept = await svc.remove_document_from_knowledge_bases("doc-1", MagicMock())

        assert removed == [{"uuid": "kb-b", "title": "B"}]
        assert kept == [{"uuid": "kb-a", "title": "A"}]

    @pytest.mark.asyncio
    async def test_no_sources_is_a_noop(self):
        from app.services import knowledge_service as svc

        with patch.object(svc.KnowledgeBaseSource, "find", return_value=_find_returning([])), \
             patch.object(svc, "remove_source", AsyncMock()) as remove:
            assert await svc.remove_document_from_knowledge_bases("doc-1", MagicMock()) == ([], [])
        remove.assert_not_awaited()


class TestDeleteRoute:
    async def _delete(self, client, url, removed=None):
        user = _make_user()
        cookies, headers = _auth_cookies()
        with patch("app.dependencies.decode_token", return_value={"sub": "testuser", "type": "access"}), \
             patch("app.dependencies.User") as MockUser, \
             patch("app.routers.files.file_service") as mock_files, \
             patch("app.routers.files.knowledge_service") as mock_kb:
            MockUser.find_one = AsyncMock(return_value=user)
            mock_files.delete_document = AsyncMock(return_value=True)
            mock_kb.remove_document_from_knowledge_bases = AsyncMock(return_value=removed or ([], []))
            resp = await client.delete(url, cookies=cookies, headers=headers)
        return resp, mock_kb.remove_document_from_knowledge_bases

    @pytest.mark.asyncio
    async def test_default_keeps_kb_copies(self, client):
        resp, remove = await self._delete(client, "/api/files/doc-1")
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}
        remove.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_flag_removes_and_reports(self, client):
        result = ([{"uuid": "kb-1", "title": "Mine"}], [{"uuid": "kb-2", "title": "Theirs"}])
        resp, remove = await self._delete(
            client, "/api/files/doc-1?remove_from_knowledge_bases=true", removed=result,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["knowledge_bases_removed"] == [{"uuid": "kb-1", "title": "Mine"}]
        assert body["knowledge_bases_kept"] == [{"uuid": "kb-2", "title": "Theirs"}]
        assert remove.await_args.args[0] == "doc-1"
