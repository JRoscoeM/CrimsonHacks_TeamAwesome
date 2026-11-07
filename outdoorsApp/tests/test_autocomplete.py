"""Address API contract and asynchronous UI races; never make billed calls."""

import asyncio
import json
import os
import unittest
from unittest.mock import AsyncMock, patch

os.environ["WAYFINDER_SAMPLE_ONLY"] = "1"

from outdoorsApp.outdoorsApp import State
from outdoorsApp.places import autocomplete
from outdoorsApp.places.http import SourceError

PREDICTION = {"id": "test-place", "label": "350 State St, Salt Lake City, UT", "source": "google"}


class AddressApiTests(unittest.TestCase):
    def test_predictions_and_details_share_session_and_keep_key_in_headers(self):
        with patch.object(autocomplete, "enabled", return_value=True), patch.object(
            autocomplete, "request_json", return_value={"suggestions": [
                {"placePrediction": {"placeId": "test-place", "text": {"text": PREDICTION["label"]}}}
            ]}
        ) as request:
            self.assertEqual(autocomplete.suggest("350 State", "session-one"), [PREDICTION])
            body = json.loads(request.call_args.kwargs["data"])
            self.assertEqual(body["sessionToken"], "session-one")
            self.assertEqual(body["includedRegionCodes"], ["us"])
            self.assertIn("X-Goog-Api-Key", request.call_args.kwargs["headers"])
            request.return_value = {"formattedAddress": PREDICTION["label"], "location": {"latitude": 40.7, "longitude": -111.9}}
            result = autocomplete.resolve("test-place", "session-one")
            self.assertEqual(result["lat"], 40.7)
            self.assertEqual(request.call_args.kwargs["params"], {"sessionToken": "session-one"})
            self.assertEqual(request.call_args.kwargs["headers"]["X-Goog-FieldMask"], "formattedAddress,location")

    def test_short_queries_and_disabled_service_make_no_requests(self):
        with patch.object(autocomplete, "request_json") as request, patch.object(autocomplete, "enabled", return_value=False):
            self.assertEqual(autocomplete.suggest("35", "session"), [])
            with self.assertRaises(SourceError):
                autocomplete.suggest("350 State", "session")
            request.assert_not_called()

    def test_invalid_coordinates_are_rejected(self):
        with patch.object(autocomplete, "enabled", return_value=True), patch.object(
            autocomplete, "request_json", return_value={"formattedAddress": "Somewhere", "location": {"latitude": 999, "longitude": 0}}
        ), self.assertRaises(SourceError):
            autocomplete.resolve("place", "session")


class LockedState:
    """Minimal async lock facade for exercising handlers against a real State."""
    def __init__(self, state):
        object.__setattr__(self, "state", state)

    def __getattr__(self, name):
        return getattr(self.state, name)

    def __setattr__(self, name, value):
        setattr(self.state, name, value)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class AddressStateTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.state = State(_reflex_internal_init=True)
        self.locked = LockedState(self.state)
        self.enabled = patch.object(autocomplete, "enabled", return_value=True)
        self.enabled.start()
        self.addCleanup(self.enabled.stop)

    async def fetch(self, revision):
        with patch("outdoorsApp.outdoorsApp.asyncio.sleep", new_callable=AsyncMock):
            await State.fetch_address_suggestions.fn(self.locked, revision)

    async def apply(self, revision):
        return [event async for event in State.apply_address_suggestion.fn(self.locked, revision)]

    async def test_fast_typing_skips_obsolete_requests(self):
        self.state.set_location_text("350")
        old = self.state._location_revision
        self.state.set_location_text("350 State")
        with patch.object(autocomplete, "suggest", return_value=[PREDICTION]) as suggest:
            await self.fetch(old)
            suggest.assert_not_called()
            await self.fetch(self.state._location_revision)
            suggest.assert_called_once()
            self.assertEqual(self.state.location_options, [PREDICTION])
            self.assertFalse(self.state.suggestions_loading)

    async def test_late_response_cannot_replace_new_query_or_reopen_menu(self):
        for action in (lambda: self.state.set_location_text("Another address"), self.state.close_location_suggestions):
            self.state.set_location_text("350 State")
            started, finish = asyncio.Event(), asyncio.Event()
            async def delayed(*args):
                started.set()
                await finish.wait()
                return [PREDICTION]
            with patch("outdoorsApp.outdoorsApp.asyncio.to_thread", side_effect=delayed):
                task = asyncio.create_task(self.fetch(self.state._location_revision))
                await started.wait()
                action()
                finish.set()
                await task
            self.assertEqual(self.state.address_predictions, [])

    async def test_keyboard_selection_resolves_coordinates_and_requests_drives(self):
        self.state.set_location_text("350 State")
        self.state.address_predictions = [PREDICTION]
        token = self.state._address_session
        self.state.location_key("ArrowDown")
        self.assertEqual(self.state.active_location_option, "origin-option-0")
        self.state.location_key("Enter")
        revision = self.state._location_revision
        self.state.close_location_suggestions()  # blur after selection must not cancel it
        with patch.object(autocomplete, "resolve", return_value={"label": PREDICTION["label"], "lat": 40.7, "lon": -111.9}) as resolve:
            events = await self.apply(revision)
            resolve.assert_called_once_with(PREDICTION["id"], token)
        self.assertEqual(self.state.origin_lat, 40.7)
        self.assertEqual(self.state.origin_name, PREDICTION["label"])
        self.assertFalse(self.state.locating)
        self.assertEqual(self.state._address_session, "")
        self.assertEqual(events, [State.load_drives])

    async def test_service_failure_preserves_origin_and_offers_explicit_search(self):
        self.state.set_location_text("350 State")
        with patch.object(autocomplete, "suggest", side_effect=SourceError("unavailable")):
            await self.fetch(self.state._location_revision)
        self.assertIn("Press Enter", self.state.suggestions_note)
        self.assertEqual(self.state.origin_name, "Salt Lake City, UT")
        self.assertFalse(self.state.suggestions_loading)

    async def test_edit_during_selection_discards_old_coordinates(self):
        self.state.set_location_text("350 State")
        self.state.address_predictions = [PREDICTION]
        self.state.choose_address_option(PREDICTION["id"])
        started, finish = asyncio.Event(), asyncio.Event()
        async def delayed(*args):
            started.set()
            await finish.wait()
            return {"label": "Old address", "lat": 40.7, "lon": -111.9}
        with patch("outdoorsApp.outdoorsApp.asyncio.to_thread", side_effect=delayed):
            task = asyncio.create_task(self.apply(self.state._location_revision))
            await started.wait()
            self.state.choose_location_suggestion("Moab, UT")
            finish.set()
            await task
        self.assertEqual(self.state.origin_name, "Moab, UT")
        self.assertFalse(self.state.locating)

    async def test_unknown_selection_cannot_trigger_details(self):
        self.state.choose_address_option("arbitrary-id")
        with patch.object(autocomplete, "resolve") as resolve:
            await self.apply(self.state._location_revision)
            resolve.assert_not_called()
