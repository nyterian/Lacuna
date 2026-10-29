import json
from pathlib import Path
from streamlit.testing.v1 import AppTest
from lacuna.specification import example_request

APP = str(Path(__file__).parents[1] / 'app.py')


def test_app_loads_and_example_fills_form():
    app = AppTest.from_file(APP).run(timeout=30)
    assert not app.exception
    assert [tab.label for tab in app.tabs] == ['Specification', 'Results', 'Field gaps', 'Topic branches', 'Artifacts', 'Runs']
    next(b for b in app.button if b.label == 'Load example specification').click().run()
    assert 'Generative AI' in app.text_input[0].value
    assert not app.exception


def test_app_invalid_form_has_actionable_error():
    app = AppTest.from_file(APP).run(timeout=30)
    next(b for b in app.button if b.label == 'Run discovery').click().run()
    assert app.error
    assert not app.exception
    assert all('profile' in error.value or 'concept_groups' in error.value or 'title' in error.value or 'description' in error.value for error in app.error)


def test_form_builds_reusable_request_json():
    app = AppTest.from_file(APP).run(timeout=30)
    next(b for b in app.button if b.label == 'Load example specification').click().run()
    next(b for b in app.button if b.label == 'Build request JSON').click().run()
    assert not app.exception
    data = json.loads(app.session_state['prepared_request'])
    assert data['schema_version'] == '1.0'
    assert data['profile']['title'].startswith('Generative AI')


def test_json_mode_validates_shared_contract():
    app = AppTest.from_file(APP).run(timeout=30)
    app.radio[0].set_value('JSON').run()
    next(area for area in app.text_area if area.label == 'request.json').set_value(json.dumps(example_request())).run()
    next(b for b in app.button if b.label == 'Validate specification').click().run()
    assert app.success and not app.exception
    assert 'Valid schema_version=1.0' in app.success[0].value


def test_json_mode_rejects_unknown_fields():
    app = AppTest.from_file(APP).run(timeout=30)
    app.radio[0].set_value('JSON').run()
    request = example_request()
    request['config']['hallucinated_field'] = True
    next(area for area in app.text_area if area.label == 'request.json').set_value(json.dumps(request)).run()
    next(b for b in app.button if b.label == 'Validate specification').click().run()
    assert app.error and not app.exception
    assert 'hallucinated_field' in app.error[0].value
