"""Seed imported-history browser fixtures in an existing disposable /private/tmp DB."""

import argparse
from pathlib import Path

from backend.student_store import StudentStore


def main() -> None:
    """Add legacy rows for a known test owner; refuse databases outside temporary storage."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--owner-id', required=True)
    args = parser.parse_args()
    database = args.database.resolve()
    if not database.is_relative_to(Path('/private/tmp')) or not database.is_file():
        parser.error('Use an existing disposable database under /private/tmp')
    root = StudentStore(database)
    profile = root.get_user_by_id(args.owner_id)
    if not profile or not profile['identifier'].startswith('guest:'):
        parser.error('Use the guest owner_id from the disposable browser session')
    owner = StudentStore(database, identifier=profile['identifier'])
    thread = owner.create_thread(name='Imported bookmarks QA', quick_chat=True, model_id='mock', support_mode='critical-thinking')
    owner.add_message(thread, 'user', 'Historical idea without a saved stage.', metadata={'starred': True})
    owner.add_message(thread, 'assistant', 'Saved ethics explanation from Lecture Help.', metadata={
        'starred': True, 'thinking_stage': 'deep_analysis', 'interaction_intent': 'lecture_help'})
    owner.add_message(thread, 'user', 'Unstarred work must stay out of My work.', metadata={'thinking_stage': 'problem_identification'})
    print(thread)


if __name__ == '__main__':
    main()
