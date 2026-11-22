"""Disposable scripted model boundary for rendered project-brief tests; never use personal data."""
import os
from pathlib import Path

from backend import owner_context
from backend.domain import CoachRequest, EducationalAssessment, ProjectBrief, ProviderAssessmentResult
from backend.mock_provider import DeterministicCoachProvider
from backend.prompts.project_brief import PROJECT_BRIEF_TASK

if not Path(os.environ['APP_DATABASE_PATH']).resolve().is_relative_to('/private/tmp'):
    raise RuntimeError('Project brief browser fixtures require a disposable /private/tmp database')


class ScriptedBriefModel(DeterministicCoachProvider):
    """Keep normal deterministic chat and supply a known summary only for the explicit fixture."""
    provider_id = 'scripted-brief'

    def assess(self, request: CoachRequest) -> ProviderAssessmentResult:
        """Respond at the external model boundary without a network call or inferred fixture facts."""
        if request.student_message != PROJECT_BRIEF_TASK:
            return super().assess(request)
        text = '\n'.join(row['content'] for row in request.history if row['role'] == 'user')
        brief = ProjectBrief()
        quotes = [
            'Older residents near campus need more time to cross safely.',
            'The signal changes before slower pedestrians finish crossing.',
            'We might try a button for extra crossing time, but have not selected an idea.',
            'We have not tested whether residents can find and use the button.',
        ]
        if all(quote in text for quote in quotes):
            brief = ProjectBrief.model_validate({
                'who_and_why': {'text': 'Older residents crossing near campus need enough time to cross safely.', 'evidence': [quotes[0]]},
                'problem': {'text': 'The crossing signal changes before slower pedestrians finish crossing.', 'evidence': [quotes[1]]},
                'current_idea': {'text': 'Considering a button that requests extra crossing time; no option is selected yet.', 'evidence': [quotes[2]]},
                'what_matters': {'text': None, 'evidence': []},
                'still_to_explore': {'text': 'Whether residents could find and use the button remains untested.', 'evidence': [quotes[3]]},
            })
        return ProviderAssessmentResult(response_text='Summary ready.', assessment=EducationalAssessment(
            current_stage=request.current_stage, project_brief=brief))


owner_context.configured_coach_provider = ScriptedBriefModel
from backend.api import create_app
app = create_app()
