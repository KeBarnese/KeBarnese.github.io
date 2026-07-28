# Records source folder

This folder is the **permanent home** for the scanned documents that appear on
the family-history site. `build_site.py` copies it into the built site
(`gUclVDpu/records/`) on every rebuild, so files placed here survive rebuilds.

## Organization

    census/        U.S. federal & state census pages
    military/      draft cards, service records, muster rolls, POW rolls
    immigration/   ship manifests, naturalization papers   (empty — awaiting uploads)
    vital/         birth / marriage / death acts (incl. Mexican civil register)
    graves/        headstone photos and cemetery images

## Naming convention

Lowercase, hyphen-separated, descriptive:

    surname-firstname-doctype[-detail].ext
    e.g.  sanchez-john-draft-front.jpg
          bell-james-csr-04.jpg
          ramona-birth-1898-p1.pdf

## Adding new documents

1. Drop the file in the right category folder with a name like the above.
2. Add a line to the person's list in the `DOCS` dict in `build_site.py`:
       ("Category", "records/<cat>/<file>", "Human-readable label")
   (`populate_records.py` documents the current upload→filename mapping.)
3. Rebuild.

Files currently placed: see `populate_records.py` (the verified upload→name map).
