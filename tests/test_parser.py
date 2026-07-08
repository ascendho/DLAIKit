from dlaikit.parser import (
    clean_lines,
    extract_course_info,
    extract_lesson_data,
    extract_resource_links,
    extract_transcript_from_lines,
    find_lesson_links,
)


HTML = """
<html>
  <head><title>Introduction</title></head>
  <body>
    <nav>
      <a href="/courses/building-coding-agents-with-tool-execution/lesson/deetno/introduction">Intro</a>
      <a href="/courses/building-coding-agents-with-tool-execution/lesson/abc123/tools">Tools</a>
      <a href="/courses/other-course/lesson/xyz/other">Other</a>
    </nav>
    <main>
      <h1>Introduction</h1>
      <p>Welcome to this lesson where we discuss coding agents and their tool execution workflow.</p>
      <p>This second transcript paragraph is long enough to be captured by the heuristic.</p>
      <button>Show Transcript</button>
    </main>
  </body>
</html>
"""


def test_extract_transcript_from_lines():
    lines, _ = clean_lines(HTML)

    transcript = extract_transcript_from_lines(lines)

    assert "coding agents" in transcript
    assert "second transcript paragraph" in transcript


def test_find_lesson_links_preserves_course_order():
    _, soup = clean_lines(HTML)

    links = find_lesson_links(
        soup,
        "https://learn.deeplearning.ai/courses/building-coding-agents-with-tool-execution/lesson/deetno/introduction",
    )

    assert links == [
        "https://learn.deeplearning.ai/courses/building-coding-agents-with-tool-execution/lesson/deetno/introduction",
        "https://learn.deeplearning.ai/courses/building-coding-agents-with-tool-execution/lesson/abc123/tools",
    ]


def test_extract_lesson_data_returns_title_and_transcript():
    title, transcript = extract_lesson_data(HTML)

    assert title == "Introduction"
    assert "tool execution workflow" in transcript


def test_extract_course_info_from_public_course_page():
    html = """
    <html>
      <head>
        <title>Browser title</title>
        <meta name="description" content="Learn to build coding agents that can execute tools safely.">
      </head>
      <body>
        <main>
          <h1>Building Coding Agents with Tool Execution</h1>
          <p>Intermediate course. 1h21m. Learn to build agents for practical coding workflows.</p>
          <h2>Instructors</h2>
          <p>Tereza Tizkova</p>
          <p>Francesco Zuppichinni</p>
          <h2>What you'll learn</h2>
          <ul>
            <li>Build an agent that runs Python code.</li>
            <li>Use a sandbox for safer tool execution.</li>
          </ul>
          <section>
            <h2>Course Outline</h2>
            <article>
              <a href="https://learn.deeplearning.ai/courses/building-coding-agents-with-tool-execution/lesson/deetno/introduction">
                <h3>Introduction</h3>
                <span>Video</span>
                <span>3m</span>
              </a>
            </article>
            <article>
              <a href="https://learn.deeplearning.ai/courses/building-coding-agents-with-tool-execution/lesson/abc123/data-analyst-agent">
                <h3>Data analyst agent</h3>
                <span>Code example</span>
                <span>12m</span>
              </a>
            </article>
            <article>
              <a href="https://learn.deeplearning.ai/courses/building-coding-agents-with-tool-execution/lesson/quiz1/graded-assignment">
                <h3>Build a full-stack agent</h3>
                <span>Graded assignment</span>
              </a>
            </article>
          </section>
          <a href="https://github.com/example/course-notebooks">Course notebooks</a>
          <a href="https://www.deeplearning.ai/">DeepLearning.AI Home</a>
        </main>
      </body>
    </html>
    """

    course = extract_course_info(
        html,
        "https://www.deeplearning.ai/courses/building-coding-agents-with-tool-execution",
    )

    assert course.slug == "building-coding-agents-with-tool-execution"
    assert course.title == "Building Coding Agents with Tool Execution"
    assert course.description == "Learn to build coding agents that can execute tools safely."
    assert course.level == "Intermediate"
    assert course.duration == "1h21m"
    assert course.instructors == ["Tereza Tizkova", "Francesco Zuppichinni"]
    assert course.learning_objectives == [
        "Build an agent that runs Python code.",
        "Use a sandbox for safer tool execution.",
    ]
    assert [lesson.kind for lesson in course.lessons] == ["video", "code", "assignment"]
    assert course.lessons[1].duration == "12m"
    assert course.resources[0].kind == "repository"


def test_extract_resource_links_filters_navigation():
    html = """
    <html>
      <body>
        <a href="/courses/building-coding-agents-with-tool-execution/lesson/deetno/introduction">Intro</a>
        <a href="https://github.com/example/agent">Source code</a>
        <a href="https://example.test/notebooks/agent.ipynb">Notebook</a>
        <a href="https://www.deeplearning.ai/resources/">Resources</a>
        <a href="https://example.test/privacy">Privacy</a>
      </body>
    </html>
    """

    resources = extract_resource_links(
        html,
        "https://learn.deeplearning.ai/courses/building-coding-agents-with-tool-execution/lesson/deetno/introduction",
        lesson_url="https://learn.deeplearning.ai/courses/building-coding-agents-with-tool-execution/lesson/deetno/introduction",
    )

    assert [resource.kind for resource in resources] == ["repository", "notebook"]
