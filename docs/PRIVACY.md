# What data Music Bingo keeps

This is for people who run Music Bingo and want to tell their hosts and players what is stored. It describes the software as it
is written; you are the one running it, so what you promise others is up to you (and the law where you live).

## What is stored, and where

Everything is in the database (the `bingo-db` volume) on your own server. There is **no analytics, no tracking, no advertising
and no data sent to the author**. Music Bingo never asks for an e-mail address.

| Who | What | Why |
| --- | --- | --- |
| **Hosts** (accounts you create) | username, a hashed password (never the password itself), whether they are an admin, their color theme | to log in |
| Hosts who connect Spotify | the Spotify login (access and refresh tokens) for their Spotify account | to play music and read their playlists; removed when the host disconnects, when Spotify revokes it, or when the account is deleted |
| Hosts' content | games and their history, saved playlists (names and Spotify playlist ids, not the songs' audio), events with an optional logo image, paper-card settings | the game itself |
| **Players** | the name they typed (up to 40 characters), their bingo card, any bingo claims, a random token that identifies their phone in that game | to run the game; no e-mail, phone number, address or device details are stored |
| The app | settings an admin saves (public address, Spotify client id and secret) | to run |

The web server's own log (`docker compose logs app`) records the visitor's IP address and the page asked for, like any web
server. The one-time code in the Spotify sign-in redirect is blanked out of it. Nothing writes the log to disk beyond Docker's own
log files; set Docker's log rotation if you want them to expire.

## Cookies

All are first-party, used only to run the app, and none is for advertising:

| Cookie | Who | How long | Used for |
| --- | --- | --- | --- |
| `host_session` | hosts | 7 days | staying logged in (signed; stops working when the password changes) |
| `bingo_csrf` | everyone | 30 days | protects forms against forged requests |
| `bingo_player_<GAME CODE>` | players | 2 days | tells the game which player this phone is |
| `host_state`, `host_flash` | hosts | 10 minutes, 30 seconds | the Spotify sign-in round trip, and one-time messages |

## Third parties

- **Spotify.** A host who connects Spotify talks to Spotify from the server and, for the in-browser player, from their browser
  (the page loads Spotify's player script). Players' phones do not contact Spotify through the app.
- Nothing else. Fonts, scripts and images are served from your own server.

## Deleting data

- **A game:** the host's **Delete** (on Game History or Saved Games) removes the game with its players, their cards, every bingo
  claim and the played-song list.
- **A player in a lobby:** the host's **Kick**, or the player's own "Not you? Join as someone else", removes them and their card.
- **A host account:** **Admin → Delete** on the user removes the account and everything it owns: all its games (with their
  players, cards and history), Play Alone sessions, events and logos, saved playlists and the saved Spotify login.
- **Event logos:** **Options → Events** removes a logo, or the whole event.

Nothing is deleted automatically, so old games stay until someone deletes them. If you want players' names gone after an event,
delete the game (or ask hosts to).

## Backups

A database backup contains all of the above, including password hashes and any Spotify client secret that was saved in the
app, so keep backups private and delete old ones (see `BACKUP_AND_UPDATE.md`).
