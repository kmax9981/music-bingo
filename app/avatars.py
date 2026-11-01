"""Player pictures: an animal and a color, chosen when joining (or picked for the player). Stored as short keys, never as
free text, so only these values can ever reach a page. The emoji look a little different on each kind of device."""
import random

AVATARS = [('fox', '🦊'), ('panda', '🐼'), ('lion', '🦁'), ('tiger', '🐯'), ('bear', '🐻'), ('koala', '🐨'),
           ('monkey', '🐵'), ('frog', '🐸'), ('penguin', '🐧'), ('owl', '🦉'), ('duck', '🦆'), ('turtle', '🐢'),
           ('octopus', '🐙'), ('butterfly', '🦋'), ('bee', '🐝'), ('dolphin', '🐬'), ('giraffe', '🦒'), ('elephant', '🐘'),
           ('kangaroo', '🦘'), ('rabbit', '🐰'), ('dog', '🐶'), ('cat', '🐱'), ('unicorn', '🦄'), ('dinosaur', '🦖')]
COLORS = ['purple', 'orange', 'blue', 'green', 'pink', 'yellow', 'red', 'teal', 'indigo', 'lime', 'brown', 'slate']
_EMOJI = dict(AVATARS)


def avatar_info(avatar, color) -> dict:
    """What a page needs to draw a player's picture; a player with none gets a plain paw print."""
    a = avatar if avatar in _EMOJI else ''
    return {'key': a, 'emoji': _EMOJI.get(a, '🐾'), 'label': a or 'player', 'color': color if color in COLORS else 'purple'}


def choose(avatar, color, taken) -> tuple:
    """The player's own choice where it is valid, otherwise an animal nobody else in the game has (while any is left)
    and a random color. `taken` is the list of animals already used in the game."""
    a = str(avatar or '').strip().lower()
    if a not in _EMOJI:
        free = [k for k, _ in AVATARS if k not in set(taken)]
        a = random.choice(free or [k for k, _ in AVATARS])
    c = str(color or '').strip().lower()
    if c not in COLORS:
        c = random.choice(COLORS)
    return a, c
