# Account language

MediaHub stores `en` or `da` in the authenticated user's preferences. The initial administrator wizard and managed-user editor accept a language; changing only a name, role or password preserves the saved language. Language changes preserve appearance settings. Ordinary users can change their own language from their app page.

Hub SSO returns the account language on both exchange and session validation. MediaSeed and MediaVPN use that identity rather than the browser locale or an administrator-wide setting. Open app pages recheck the identity on focus and once per minute; subsequent UI refreshes use the current language. An unavailable identity request never changes an existing account's saved preference.

Standalone MediaSeed/MediaVPN administrators choose a language at creation. Existing standalone accounts receive `da` during the additive database migration, matching the previous Danish interface. The migration preserves password hashes and sessions; hub-managed identities always use the hub preference.

## Maintaining messages

Use English source keys in `t()` and add Danish translations to `frontend/src/locales/da.json`. Use named placeholders for account names, app names, versions, addresses and file names. Do not translate arbitrary API data or user content. `Intl` date, number and country formatting should use the account locale.

The independent apps ship their own `static/i18n.js` catalogs and translator. Static text and accessibility attributes are captured before remote data is rendered. Dynamic labels call `t()` explicitly. The extension includes the same MediaSeed catalog, loads the account language on connection and import, and refreshes it when reopening a configured popup. Its tracker-page helpers deliberately do not load the DOM translator into other websites.

Run the hub localization tests, each app's `test_localization.py`, and the JavaScript UI tests after changing messages. These check translation keys, placeholders, static labels, reversible language changes, standalone account migration and real in-process SSO roundtrips for both apps. Rebuild extension archives with `python browser-extension/build.py` after extension changes. Browser names, product names, protocols and literal commands may remain unchanged in both languages.

Third-party app interfaces such as Plex, Jellyfin and FjordHub keep their upstream language settings. MediaHub's navigation, configuration and status for those apps follow the MediaHub account language.
