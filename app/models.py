from sqlalchemy import String, Integer, Boolean, DateTime, ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
import sqlalchemy as sa
from datetime import datetime
from .db import Base
class HostUser(Base):
    __tablename__ = 'host_users'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    # color theme the host picked on the Account page (see themes.py); players see their host's theme
    theme: Mapped[str] = mapped_column(String(24), nullable=False, default='midnight', server_default='midnight')
    # the host's own colors 'rrggbb-rrggbb-rrggbb' (background, buttons, highlight), kept even while another theme is picked
    # True while the account still has a password somebody else knows (generated at first run, made by the reset tool or set by an admin): the host must choose their own before using the app
    must_change_password: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=sa.false())
    custom_colors: Mapped[str] = mapped_column(String(20), nullable=False, default='', server_default='')


class SavedPlaylist(Base):
    __tablename__ = 'saved_playlists'
    # One entry per host per Spotify playlist (so a host can keep a private copy of one someone else shared).
    # Existing databases are migrated in main._migrate_saved_playlists().
    __table_args__ = (UniqueConstraint('created_by_user_id', 'spotify_playlist_id', name='uq_saved_playlist_owner'),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    spotify_playlist_id: Mapped[str] = mapped_column(String(128), nullable=False)
    created_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    # Public: every host can use it. Private: only the host who added it sees it. Only that host can
    # change this, rename or delete it.
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=sa.true())
    # How many of the playlist's songs Spotify marks explicit (None = not checked yet)
    explicit_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    track_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    explicit_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
class Game(Base):
    playback_device_id = sa.Column(sa.Text, nullable=True)
    playback_started_at = sa.Column(sa.DateTime, nullable=True)
    __tablename__ = 'games'

    owner_key: Mapped[str] = mapped_column(String(64), nullable=False, server_default='default', index=True)
    game_type: Mapped[str] = mapped_column(String(16), nullable=False, server_default='hosted')
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(8), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    spotify_playlist_id: Mapped[str] = mapped_column(String(128), nullable=False)

    playlist_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default='lobby')  # lobby|started|ended
    continue_seq: Mapped[int] = mapped_column(Integer, nullable=False, server_default='0')
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Paper cards: the event (name and/or logo) shown in their center square, and whether the printed
    # cards carry a "join on your phone" line. Existing databases: main._migrate_paper_cards().
    # Saved games: games the host keeps to run over and over (with their paper cards). They live on the Saved
    # Games page instead of only Game History. sessions_played counts how many times the game has been started.
    is_saved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=sa.false())
    # Bingo hints: 'off', 'all' (every phone player sees which column the song is in) or 'optin' (each player chooses)
    hint_mode: Mapped[str] = mapped_column(String(8), nullable=False, default='off', server_default='off')
    cohost_token: Mapped[str | None] = mapped_column(String(32), nullable=True)   # the secret in the co-host link; empty when the link is off
    win_pattern: Mapped[str] = mapped_column(String(10), nullable=False, default='line', server_default='line')   # what counts as bingo (see cards.WIN_PATTERNS)
    room_reveal: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=sa.false())
    room_sound: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=sa.false())
    sessions_played: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default='0')
    last_played_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    event_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    paper_join_footer: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=sa.true())
    # theme spec (see themes.py) the paper cards are colored with (white paper, colored lines and centre square); '' = plain black and white
    paper_theme: Mapped[str] = mapped_column(String(40), nullable=False, default='', server_default='')

    players = relationship('Player', back_populates='game', cascade='all, delete-orphan')
    played = relationship('PlayedTrack', back_populates='game', cascade='all, delete-orphan')
    claims = relationship('BingoClaim', back_populates='game', cascade='all, delete-orphan')


class Player(Base):
    __tablename__ = 'players'
    __table_args__ = (
        UniqueConstraint('game_id', 'number', name='uq_player_game_number'),
        UniqueConstraint('game_id', 'token', name='uq_player_game_token'),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    game_id: Mapped[int] = mapped_column(Integer, ForeignKey('games.id'), nullable=False)
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(40), nullable=False)
    admitted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    token: Mapped[str] = mapped_column(String(128), nullable=False)  # for reconnect/cookies
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    # A printed paper card rather than a phone player: no phone, never in the admit list. Paper cards are
    # numbered 1, 2, 3... per game (card_number); phone players are shown by name only.
    is_paper: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=sa.false())
    card_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    avatar: Mapped[str] = mapped_column(String(16), nullable=False, default='', server_default='')          # an animal from avatars.AVATARS
    avatar_color: Mapped[str] = mapped_column(String(10), nullable=False, default='', server_default='')   # one of avatars.COLORS

    game = relationship('Game', back_populates='players')
    squares = relationship('CardSquare', back_populates='player', cascade='all, delete-orphan')
    claims = relationship('BingoClaim', back_populates='player', cascade='all, delete-orphan')

class CardSquare(Base):
    __tablename__ = 'card_squares'
    __table_args__ = (
        UniqueConstraint('player_id', 'pos', name='uq_square_player_pos'),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    player_id: Mapped[int] = mapped_column(Integer, ForeignKey('players.id'), nullable=False)
    pos: Mapped[int] = mapped_column(Integer, nullable=False)  # 0..24 row-major
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    is_free: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    marked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    player = relationship('Player', back_populates='squares')


class PlayedTrack(Base):
    __tablename__ = 'played_tracks'
    __table_args__ = (
        UniqueConstraint('game_id', 'seq', name='uq_played_game_seq'),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    game_id: Mapped[int] = mapped_column(Integer, ForeignKey('games.id'), nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    spotify_track_id: Mapped[str] = mapped_column(String(128), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    artist: Mapped[str] = mapped_column(String(200), nullable=False)
    played_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    game = relationship('Game', back_populates='played')

class BingoClaim(Base):
    __tablename__ = 'bingo_claims'

    # Round index (host Continue increments games.continue_seq). Used to scope claims per round.
    claim_round = sa.Column(sa.Integer, default=0, nullable=False)
    pattern = sa.Column(sa.String(10), default='line', server_default='line', nullable=False)   # the win pattern in force when the claim was made
    # True when a claim is rejected because it is a reuse attempt within the same round.
    reuse_reject = sa.Column(sa.Boolean, default=False, nullable=False)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    game_id: Mapped[int] = mapped_column(Integer, ForeignKey('games.id'), nullable=False, index=True)
    player_id: Mapped[int] = mapped_column(Integer, ForeignKey('players.id'), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    auto_valid: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default='pending', nullable=False)  # pending|accepted|rejected
    detail: Mapped[str] = mapped_column(Text, default='', nullable=False)

    game = relationship('Game', back_populates='claims')
    player = relationship('Player', back_populates='claims')

class Event(Base):
    """A host's saved event for paper cards: a name, a logo, or both. Private to that host."""
    __tablename__ = 'events'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    host_user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False, default='')
    logo: Mapped[bytes | None] = mapped_column(sa.LargeBinary, nullable=True)  # PNG/JPEG, shrunk in the browser
    logo_mime: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class HostSpotifyToken(Base):
    __tablename__ = 'host_spotify_token'
    owner_key: Mapped[str] = mapped_column(String(64), nullable=False, server_default='default')

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    host_user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("host_users.id"), nullable=True, index=True)
    access_token: Mapped[str] = mapped_column(Text, nullable=False)
    refresh_token: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class AppSetting(Base):
    """Settings an admin can change in the app (the setup screen and the Admin page) instead of in the env file:
    PUBLIC_BASE_URL and the Spotify developer app's id, secret and redirect address. A value set in the environment wins."""
    __tablename__ = 'app_settings'
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False, default='')
