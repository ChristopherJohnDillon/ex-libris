# Changelog

## 1.0.1

Fixes from a full review of 1.0.0:

- A number like `inf` in an imported CSV (or the API) no longer breaks browsing; numbers must be sensible.
- The public view no longer writes to the data folder when visited, and answers `HEAD` requests (uptime monitors).
- Health checks answer at once even while covers are being fetched; cover downloads run in their own small lane and Open Library covers are now downloaded in the background, so the public view shows them straight away.
- Uploaded images: very large images are refused before decoding (no memory spikes), and phone photos are turned the right way up.
- A network blip no longer stops a book's cover from ever being looked for again.
- Background tasks never overwrite a cover, year or series you set while they were running; a genre you clear stays cleared.
- The optional AI now really does write a weekly "fun facts" card on the library's stats page.
- Edits work behind reverse proxies that set `X-Forwarded-Host`.
- A `/scan?isbn=` link only looks a book up; it never adds it.
- Friendlier handling of odd CSV rows, a read-only data folder, and files restored with the wrong owner.
- Database upgrades are atomic; the Docker health check follows `EXLIBRIS_PORT`; releases run the tests first.

## 1.0.0

First release.
