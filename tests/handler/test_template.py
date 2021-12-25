"""Template tests."""
# pylint: disable=missing-docstring


from config.custom_components.hacs.utils.template import render_template


class MockRelease:
    prerelease = True


def test_render_template(repository):
    content = "ABC"
    render_template(content, repository)
    repository.releases.last_release_object = MockRelease()
    render_template(content, repository)
