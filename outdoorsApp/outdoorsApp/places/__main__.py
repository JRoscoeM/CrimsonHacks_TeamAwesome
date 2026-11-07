"""Query the places cache from a terminal.

    py -m outdoorsApp.places                                  # summary
    py -m outdoorsApp.places --kind campground --activity hiking --near 37.2,-112.99 --within 25
    py -m outdoorsApp.places --text arches
    py -m outdoorsApp.places --id nps:zion --raw              # one place, full record
"""

import argparse
import json
import sys

from .store import find_places, get_place, stats


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--id", help="show one place by id")
    parser.add_argument("--raw", action="store_true", help="with --id: include the raw API record")
    parser.add_argument("--kind", action="append", help="repeatable, e.g. --kind state_park --kind national_park")
    parser.add_argument("--activity", action="append", default=[], help="repeatable; all must match")
    parser.add_argument("--text", help="search name/description")
    parser.add_argument("--near", help="lat,lon")
    parser.add_argument("--within", type=float, help="miles, with --near")
    parser.add_argument("--wheelchair", action="store_true")
    parser.add_argument("--restrooms", action="store_true")
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--json", action="store_true", help="print JSON")
    args = parser.parse_args(argv)

    if args.id:
        place = get_place(args.id)
        if not place:
            print(f"No place with id {args.id!r}")
            return 1
        print(json.dumps(place.to_dict(include_raw=args.raw), indent=2))
        return 0

    filters = (args.kind, args.activity, args.text, args.near, args.wheelchair, args.restrooms)
    if not any(filters):
        print(json.dumps(stats(), indent=2))
        return 0

    near = tuple(float(x) for x in args.near.split(",")) if args.near else None
    places = find_places(kind=args.kind, activities=args.activity, text=args.text, near=near,
                         within_mi=args.within, wheelchair=True if args.wheelchair else None,
                         restrooms=True if args.restrooms else None, limit=args.limit)
    if args.json:
        print(json.dumps([p.to_dict() for p in places], indent=2))
        return 0
    for p in places:
        dist = f"{p.distance_mi:>6.1f} mi  " if p.distance_mi is not None else ""
        print(f"{dist}{p.kind_label:<18} {p.name:<45} {p.id}")
    print(f"\n{len(places)} result(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
