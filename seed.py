import argparse

from app import create_app
from app.seeders.demo_seeder import seed_demo_data


def main():
    parser = argparse.ArgumentParser(description="Seed demo data for the student management system")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Clear existing demo data and reseed",
    )
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        seed_demo_data(force=args.force)


if __name__ == "__main__":
    main()
