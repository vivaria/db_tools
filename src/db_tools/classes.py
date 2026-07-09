

import dataclasses
import json
from collections import UserDict
from pathlib import Path
from typing import Any, Optional, Union


# ---------------------------------------------------------------------------
# Card metadata
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class Card:
    """Static catalog metadata for one card, as embedded in a card sub-dict.

    `id` is DuelingBook's catalog id for the card (shared by every physical
    copy of that card that shows up anywhere in the replay) - it's what
    `CardRegistry` keys on to guarantee reuse. `object_id` is *not* stored
    here since it identifies one physical copy within a single duel, not
    the card itself; callers that need to track a specific copy (e.g.
    `ZoneCard`) should keep the object_id alongside their reference to
    this `Card`, not inside it.
    """

    name: str = "Unknown"
    id: Optional[int] = None
    card_type: Optional[str] = None        # "Monster" | "Spell" | "Trap"
    type: Optional[str] = None             # monster type, e.g. "Effect", "Normal", "Fusion"
    attribute: Optional[str] = None
    level: Optional[int] = None
    atk: Optional[int] = None
    def_: Optional[int] = None
    ability: Optional[str] = None          # e.g. "Effect", "Tuner"
    effect: Optional[str] = None           # full effect / flavor text
    scale: Optional[int] = None            # pendulum scale
    is_effect: Optional[bool] = None
    pendulum: Optional[bool] = None
    pendulum_effect: Optional[str] = None
    flip: Optional[bool] = None
    custom: Optional[bool] = None
    serial_number: Optional[str] = None
    tcg: Optional[bool] = None
    ocg: Optional[bool] = None
    tcg_limit: Optional[int] = None
    ocg_limit: Optional[int] = None
    rush: Optional[bool] = None
    points: Optional[int] = None
    monster_color: Optional[str] = None
    arrows: Optional[str] = None
    pic: Optional[str] = None
    treated_as: Optional[str] = None
    raw: dict = dataclasses.field(default_factory=dict, repr=False)

    # Fields whose raw JSON value can be passed straight through untouched.
    _PASSTHROUGH_FIELDS = (
        "id", "card_type", "type", "attribute", "level", "ability", "effect",
        "scale", "pendulum_effect", "serial_number", "tcg_limit", "ocg_limit",
        "points", "monster_color", "arrows", "pic", "treated_as",
    )

    @classmethod
    def from_dict(cls, data: dict) -> "Card":
        """Build a `Card` from one raw card sub-dict. Always succeeds -
        an unknown/missing dict just yields a placeholder `Card`."""
        kwargs = {k: data[k] for k in cls._PASSTHROUGH_FIELDS if k in data}
        return cls(
            name=data.get("name", "Unknown"),
            def_=int(data.get("def")),
            atk=int(data.get("atk")),
            is_effect=bool(data.get("is_effect")),
            pendulum=bool(data.get("pendulum")),
            flip=bool(data.get("flip")),
            custom=bool(data.get("custom")),
            tcg=bool(data.get("tcg")),
            ocg=bool(data.get("ocg")),
            rush=bool(data.get("rush")),
            raw=data,
            **kwargs,
        )


class CardRegistry(UserDict):
    """Dict-like cache of full `Card` metadata, keyed by card name.

    A `CardRegistry` is meant to be instantiated *outside* of any single
    `Replay` (e.g. shared across many replays) and passed in wherever one
    is needed. `Play` objects themselves only ever hold a card's bare
    `name` string (see `Play.card`/`Play.cards`), keeping them light -
    the full `Card` metadata lives here instead, and is only materialized
    when a caller explicitly asks for it via `registry["Some Card"]` or
    `registry.get("Some Card")`, exactly like a normal dict.
    """

    def add(self, data: dict) -> str:
        """Register (or upgrade) the `Card` described by a card sub-dict,
        returning its name. The *first* time a given name is seen, a
        fresh `Card` is built and cached; every subsequent call for that
        same name upgrades the previously cached `Card` in place with the
        latest dict's data, so anything already holding a reference to it
        (via `self[name]`) still sees the enriched data.
        """
        name = data.get("name")
        cached = self.data.get(name)

        if cached is None:
            self.data[name] = Card.from_dict(data)
            return name

        # Upgrade an earlier placeholder in place, so every reference
        # obtained before now still sees the enriched data through the
        # same shared instance.
        enriched = Card.from_dict(data)
        for f in dataclasses.fields(Card):
            setattr(cached, f.name, getattr(enriched, f.name))
        return name


# ---------------------------------------------------------------------------
# Play parsing
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class LogEntry:
    """One entry of a play's `log` field."""

    username: Optional[str] = None
    type: Optional[str] = None
    public_log: Optional[str] = None
    private_log: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> Optional["LogEntry"]:
        if not isinstance(data, dict):
            return None
        return cls(
            username=data.get("username"),
            type=data.get("type"),
            public_log=data.get("public_log"),
            private_log=data.get("private_log"),
        )


@dataclasses.dataclass
class Play:
    """One event from a replay's `plays` array.

    `play` is the only field guaranteed to be present; every other field is
    Optional and will simply be `None` (or empty) for play types that don't
    carry that piece of data. `raw` always holds the untouched source dict.

    DuelingBook replays are a flat, heterogeneous list of event dicts -
    every event has a `play` field naming its type (e.g. "Attack",
    "Draw card", "Life points", ...), but the *rest* of the keys present on
    any given event vary a lot depending on that type (see the big list of
    play types in the project README / gamestates.py notes).

    Rather than modelling every play type as its own class, `Play` is a
    single flat dataclass with one optional field per key that's ever been
    observed across the cataloged play types. Any event can be losslessly
    converted to a `Play` via `Play.from_dict`, and the original dict is
    always kept around on `.raw` so nothing is ever lost even for keys this
    dataclass doesn't know about yet.

    Field type notes:
        log
            Usually a single log dict (`{"public_log", "private_log"?,
            "type", "username"}`), normalised into a `LogEntry`. A few play
            types (e.g. "Pick first") carry a *list* of log entries instead
            (one per card drawn into the opening hands) - in that case
            `log` is a `list[LogEntry]`.
        card
            The bare `name` of the single card a play acts on (e.g.
            "Draw card", "To GY", "Attack"'s underlying object is
            referenced by id instead). Registered into a shared
            `CardRegistry` so that the full `Card` metadata lives outside
            of `Play` and can be looked up on demand via
            `registry.get(name)` / `registry[name]` - this keeps `Play`
            itself light. See also `CardInfo` for a separate, trimmed-down
            version used for state tracking.
        cards
            The list of card `name`s on "Pick first" (all ten opening-hand
            cards across both players). Same deal as `card` - the full
            `Card` metadata for each is available via the `CardRegistry`.
        player1 / player2
            Either a plain username string (RPS) or a small stats/info dict
            (Begin next duel, Quit duel, Admit defeat) - kept untouched as
            `Any`/dict since the shape depends on the play type.
        deck / hand / prev
            Lists of integer object_ids describing deck/hand order
            snapshots (Shuffle deck/hand, Reveal, Add random card from deck
            to hand, ...).
    """

    # -- Always present --------------------------------------------------
    play: str
    raw: dict = dataclasses.field(default_factory=dict, repr=False)

    # -- Common to almost every play type ---------------------------------
    action: Optional[str] = None
    seconds: Optional[int] = None
    username: Optional[str] = None
    log: Optional[Union[LogEntry, list]] = None

    # -- Card / object references ------------------------------------------
    card: Optional[str] = None             # card name (Draw card, To GY, Activate ST, ...) - full Card via CardRegistry
    cards: Optional[list] = None           # list[str] card names (Pick first - opening hands)
    id: Optional[int] = None               # object_id this play acts on
    attacking_id: Optional[int] = None     # Attack
    attacked_id: Optional[int] = None      # Attack
    name: Optional[str] = None             # Declare (named card/effect)
    zone: Optional[str] = None             # Move / Activate ST - destination zone token, e.g. "M2-3"
    owner: Optional[str] = None            # Move / To GY - owning username of the affected card

    # -- Life points ---------------------------------------------------
    amount: Optional[int] = None
    life: Optional[int] = None
    points: Optional[int] = None
    word: Optional[str] = None             # "increased" | "decreased"

    # -- Counters --------------------------------------------------------
    total: Optional[int] = None            # Add counter - resulting counter count

    # -- Ordering / shuffling metadata ------------------------------------
    prev: Optional[list] = None            # previous object_id order (Reveal, Shuffle hand, ...)
    deck: Optional[list] = None            # object_id order (Shuffle deck)
    hand: Optional[list] = None            # object_id order (Shuffle hand, Add random card..., To hand)
    shuffle: Optional[bool] = None

    # -- Viewing / picking -------------------------------------------------
    viewing: Optional[str] = None          # "Graveyard", "Deck (Picking 3 Cards)", ...
    callback: Optional[str] = None         # Pick 3 cards - the play type triggered once picking finishes
    line: Optional[str] = None             # Add random card from deck to hand - public-facing text

    # -- Misc / chat -------------------------------------------------------
    message: Optional[str] = None
    color: Optional[str] = None            # Duel message - chat text color

    # -- Match / game bookkeeping -------------------------------------------
    date: Optional[str] = None             # Pick first
    order: Optional[str] = None            # Pick first
    over: Optional[bool] = None            # Admit defeat
    score: Optional[str] = None            # Begin next duel, e.g. "(1-0-0)"
    starting: Optional[bool] = None        # Begin next duel
    winner: Optional[str] = None           # RPS
    player1: Optional[Any] = None          # username str, or stats/info dict
    player2: Optional[Any] = None          # username str, or stats/info dict
    player1_choice: Optional[str] = None   # RPS
    player2_choice: Optional[str] = None   # RPS

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    _FIELD_NAMES = None  # populated lazily below

    @classmethod
    def from_dict(cls, data: dict, registry: CardRegistry) -> "Play":
        """Build a `Play` from one raw event dict out of a replay's
        `plays` array. Unknown keys are silently preserved on `.raw` only.

        `registry` is the shared `CardRegistry` that `.card`/`.cards` are
        registered into - only the card's bare `name` is kept on the
        `Play` itself; the full `Card` metadata lives in `registry` and
        can be fetched later via `registry.get(name)` / `registry[name]`.
        """
        if cls._FIELD_NAMES is None:
            cls._FIELD_NAMES = {f.name for f in dataclasses.fields(cls)} - {"raw", "log", "card", "cards", "play"}

        log_data = data.get("log")
        if isinstance(log_data, list):
            log: Optional[Union[LogEntry, list]] = [
                entry for entry in (LogEntry.from_dict(e) for e in log_data) if entry is not None
            ]
        else:
            log = LogEntry.from_dict(log_data)

        if "card" in data:
            card = registry.add(data.get("card"))
        else:
            card = None

        if "cards" in data:
            cards = [registry.add(c) for c in data["cards"]]
        else:
            cards = None

        kwargs = {k: data[k] for k in cls._FIELD_NAMES if k in data}
        return cls(play=data.get("play", ""), raw=data, log=log, card=card, cards=cards, **kwargs)

# ---------------------------------------------------------------------------
# Replay metadata
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class PlayerInfo:
    """Metadata about one participant, from a replay's top-level
    `player1`/`player2`/`player3`/`player4` dict. `main`/`extra`/`side` are
    lists of catalog card ids (deck contents by object id at deck-build
    time), not `Card` instances - a `Replay`'s `plays` array is the
    authoritative, richer source for the cards actually seen in play.
    """

    username: Optional[str] = None
    user_id: Optional[int] = None
    rating: Optional[int] = None
    experience: Optional[int] = None
    nsfw: Optional[int] = None
    pic: Optional[str] = None
    default_pic: Optional[str] = None
    sleeve: Optional[str] = None
    token: Optional[str] = None
    legality: Optional[str] = None
    start: Optional[int] = None
    main_total: Optional[int] = None
    extra_total: Optional[int] = None
    side_total: Optional[int] = None
    main: list = dataclasses.field(default_factory=list)
    extra: list = dataclasses.field(default_factory=list)
    side: list = dataclasses.field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> Optional["PlayerInfo"]:
        if not isinstance(data, dict):
            return None
        return cls(
            username=data.get("username"),
            user_id=data.get("user_id"),
            rating=data.get("rating"),
            experience=data.get("experience"),
            nsfw=data.get("nsfw"),
            pic=data.get("pic"),
            default_pic=data.get("default_pic"),
            sleeve=data.get("sleeve"),
            token=data.get("token"),
            legality=data.get("legality"),
            start=data.get("start"),
            main_total=data.get("main_total"),
            extra_total=data.get("extra_total"),
            side_total=data.get("side_total"),
            main=data.get("main") or [],
            extra=data.get("extra") or [],
            side=data.get("side") or [],
        )


@dataclasses.dataclass
class Replay:
    """One full DuelingBook replay: match-level metadata plus the flat
    `plays` array, parsed into `Play` objects that only carry card
    *names*. The full `Card` metadata lives in a `CardRegistry` -
    instantiated by the caller, outside of any single `Replay`, and
    passed in to `from_dict`/`from_json_file` - so it can be shared
    across multiple replays instead of being tied to one.
    """

    id: Optional[int] = None
    date: Optional[str] = None
    format: Optional[str] = None
    rules: Optional[str] = None
    match_type: Optional[str] = None
    version: Optional[int] = None
    conceal: Optional[bool] = None
    tag_duel: Optional[bool] = None
    watching: Optional[bool] = None
    rated: Optional[bool] = None
    password: Optional[bool] = None
    links: Optional[bool] = None
    liked: Optional[bool] = None

    player1: Optional[PlayerInfo] = None
    player2: Optional[PlayerInfo] = None
    player3: Optional[PlayerInfo] = None
    player4: Optional[PlayerInfo] = None

    logs: list = dataclasses.field(default_factory=list)   # list[LogEntry] - top-level join/pairing log
    plays: list = dataclasses.field(default_factory=list)  # list[Play]

    # The (externally-owned) registry every Play's `.card`/`.cards` name
    # was registered into - kept around purely for convenience so callers
    # can look up full `Card` metadata straight off the `Replay`.
    card_registry: Optional[CardRegistry] = dataclasses.field(default=None, repr=False)

    @classmethod
    def from_dict(cls, data: dict, registry: CardRegistry) -> "Replay":
        """Build a `Replay` from a full replay JSON dict (as returned by
        the DuelingBook view-replay/ API endpoint).

        `registry` is a `CardRegistry` instantiated by the caller (so it
        can be reused/shared across multiple replays if desired) that
        every play's card name(s) are registered into.
        """
        logs = [LogEntry.from_dict(log) for log in data["logs"]]
        plays = [Play.from_dict(p, registry=registry) for p in data["plays"]]

        return cls(
            id=data.get("id"),
            date=data.get("date"),
            format=data.get("format"),
            rules=data.get("rules"),
            match_type=data.get("match_type"),
            version=data.get("version"),
            conceal=data.get("conceal"),
            tag_duel=data.get("tag_duel"),
            watching=data.get("watching"),
            rated=data.get("rated"),
            password=data.get("password"),
            links=data.get("links"),
            liked=data.get("liked"),
            player1=PlayerInfo.from_dict(data.get("player1")),
            player2=PlayerInfo.from_dict(data.get("player2")),
            player3=PlayerInfo.from_dict(data.get("player3")),
            player4=PlayerInfo.from_dict(data.get("player4")),
            logs=logs,
            plays=plays,
            card_registry=registry,
        )

    @classmethod
    def from_json_file(cls, path: Union[str, Path], registry: CardRegistry) -> "Replay":
        """Convenience loader: read and parse a replay JSON file on disk.

        `registry` is passed straight through to `from_dict` - see there
        for details.
        """
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return cls.from_dict(data, registry=registry)

