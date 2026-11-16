# Single sign-in (optional)

Hosts can sign in through an OpenID Connect provider (Authentik, Keycloak, Google and so on) instead of, or next to, the
built-in password login. **Players never sign in**, so nothing changes for them. It is off unless you set it up; with it off
the app behaves exactly as before.

## Switch it on

Register the app with your provider as a "confidential" client using the authorization code flow, with this redirect address:

    <PUBLIC_BASE_URL>/auth/oidc/callback

Then set these in the environment (compose file or `.env`):

| Setting | Meaning |
| --- | --- |
| `OIDC_ISSUER` | The provider's address for this app, for example `https://login.example.com/application/o/bingo/` (the app reads `.well-known/openid-configuration` below it) |
| `OIDC_CLIENT_ID` | The client id |
| `OIDC_CLIENT_SECRET` | The client secret (keep it in a file that is not committed) |
| `OIDC_ENABLED` | Optional: `false` switches single sign-in off while keeping every other setting (on the Admin page: the **Turn on single sign-in** box). Not set means on once the three settings above are filled in |
| `OIDC_PROVIDER_NAME` | Optional: text on the button, "Sign in with ..." |
| `OIDC_USERNAME_CLAIM` | Optional: which claim holds the user name (default `preferred_username`) |
| `OIDC_HIDE_LOCAL_LOGIN` | Optional: `true` hides the password form on the login page |

## How it behaves

* The login page gets a **Sign in with ...** button. With `OIDC_HIDE_LOCAL_LOGIN=true` the password form is hidden; it is still
  there at `/login?local=1`, which is how a local emergency account (for example `admin`) signs in if the provider is down.
* A sign-in never creates an account. The provider's user name (ignoring letter case) must match an
  existing host account (rename the host account on the Admin or Account page if the names differ), otherwise the person sees "there is no Bingo host account for you".
* Signing out of Bingo also signs the person out at the provider (so the next click on Sign in does not log them straight back in).
* The flow is the standard authorization code flow with PKCE; the person's name is read from the provider's userinfo address using
  the token handed over on the direct connection, so no extra Python packages are needed.
* Password rules, throttling and the 7 day session are unchanged: the app's own session cookie is used after sign-in.

Checks that need no server: `python3 tests/test_oidc.py`.
