# Changelog

## 1.1.0

- **Wishlist**: books you want, kept apart from the shelf (not in its search, stats, CSV or the public view). Add by search, with the scanner's new Wishlist mode, or with **Wish** on an author's page. Notes on each wish. **Got it** moves a wish onto the shelf, and adding a wished-for book any other way ticks it off.
- **Do I own this?** says when a scanned book is on a wishlist, and can add it to yours.
- Per-person wishlists when the library is behind Cloudflare Access (or another login proxy that passes the signed-in email; see `EXLIBRIS_IDENTITY_HEADER`), with optional names from `EXLIBRIS_PEOPLE`. Without one, everyone shares one list, as before.

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
