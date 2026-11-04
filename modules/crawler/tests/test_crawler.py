from dataclasses import FrozenInstanceError
from unittest.mock import patch

import pytest

from web_scraping_crawler import (
    CrawlPolicy,
    CrawlResult,
    Crawler,
    LinkReference,
    RetrievalResult,
)


class FakeRetriever:
    def __init__(self, pages):
        self.pages = pages
        self.visited = []

    def retrieve(self, url):
        self.visited.append(url)
        value = self.pages[url]
        if isinstance(value, Exception):
            raise value
        return value


class FakeLinkDiscoverer:
    def __init__(self, links):
        self.links = links
        self.visited = []

    def discover_links(self, content):
        self.visited.append(content)
        value = self.links[content]
        if isinstance(value, Exception):
            raise value
        return value


def make_policy(**overrides):
    values = {
        "allowed_domains": ("example.com",),
        "max_pages": 20,
        "max_depth": 10,
        "max_elapsed_time": 30,
    }
    values.update(overrides)
    return CrawlPolicy(**values)


def test_normalizes_seed_and_deduplicates_fragments_and_default_ports():
    policy = make_policy()
    retriever = FakeRetriever(
        {"http://example.com/a?x=1": RetrievalResult("page")}
    )
    discoverer = FakeLinkDiscoverer({"page": []})

    result = Crawler(policy).crawl(
        [
            "HTTP://EXAMPLE.COM:80/a?x=1#top",
            "http://example.com/a?x=1#other",
        ],
        retriever,
        discoverer,
    )

    assert retriever.visited == ["http://example.com/a?x=1"]
    assert result.visited_urls == ("http://example.com/a?x=1",)
    assert result.successful_urls == ("http://example.com/a?x=1",)
    assert result.termination_reason == "frontier_exhausted"


def test_reports_page_limit_when_frontier_remains():
    root = "http://example.com/"
    child = "http://example.com/child"
    retriever = FakeRetriever({root: RetrievalResult("root")})
    discoverer = FakeLinkDiscoverer({"root": [child]})

    result = Crawler(make_policy(max_pages=1)).crawl(
        [root], retriever, discoverer
    )

    assert result.visited_urls == (root,)
    assert result.discovered_urls == (child,)
    assert result.termination_reason == "page_limit"


def test_reports_time_limit_when_it_prevents_frontier_processing():
    root = "http://example.com/"
    retriever = FakeRetriever({})
    discoverer = FakeLinkDiscoverer({})

    with patch(
        "web_scraping_crawler.crawler.time.monotonic",
        side_effect=(0.0, 2.0),
    ):
        result = Crawler(make_policy(max_elapsed_time=1)).crawl(
            [root], retriever, discoverer
        )

    assert result.visited_urls == ()
    assert result.termination_reason == "time_limit"


def test_normalizes_scheme_host_https_default_port_and_fragment():
    normalized = "https://example.com/path?q=1"
    retriever = FakeRetriever({normalized: RetrievalResult("page")})
    discoverer = FakeLinkDiscoverer({"page": []})

    result = Crawler(make_policy()).crawl(
        ["HTTPS://EXAMPLE.COM:443/path?q=1#section"],
        retriever,
        discoverer,
    )

    assert result.visited_urls == (normalized,)


def test_preserves_query_strings_and_path_trailing_slash():
    urls = (
        "http://example.com/page?x=1",
        "http://example.com/page?x=2",
        "http://example.com/page/",
    )
    retriever = FakeRetriever({url: RetrievalResult(url) for url in urls})
    discoverer = FakeLinkDiscoverer({url: [] for url in urls})

    result = Crawler(make_policy()).crawl(
        urls, retriever, discoverer
    )

    assert result.visited_urls == urls


def test_resolves_links_tracks_unique_edges_and_excludes_seed_from_discovery():
    root = "http://example.com/root"
    child = "http://example.com/child"
    retriever = FakeRetriever(
        {root: RetrievalResult("root"), child: RetrievalResult("child")}
    )
    discoverer = FakeLinkDiscoverer(
        {
            "root": ["child", "/child#section", "https://other.example/x", "mailto:a@example.com"],
            "child": ["/root", "/child"],
        }
    )

    result = Crawler(make_policy()).crawl(
        [root], retriever, discoverer
    )

    assert result.visited_urls == (root, child)
    assert result.discovered_urls == (child,)
    assert result.link_edges == (
        (root, child),
        (child, root),
        (child, child),
    )
    assert result.edge_count == 3


def test_traverses_in_fifo_order():
    root = "http://example.com/"
    first = "http://example.com/a"
    second = "http://example.com/b"
    third = "http://example.com/c"
    retriever = FakeRetriever(
        {url: RetrievalResult(url) for url in (root, first, second, third)}
    )
    discoverer = FakeLinkDiscoverer(
        {
            root: ["/a", "/b"],
            first: ["/c"],
            second: [],
            third: [],
        }
    )

    result = Crawler(make_policy()).crawl(
        [root], retriever, discoverer
    )

    assert result.visited_urls == (root, first, second, third)


def test_requires_seed_to_be_inside_explicit_exact_scope():
    crawler = Crawler(make_policy())

    with pytest.raises(ValueError, match="outside"):
        crawler.crawl(
            ["http://sub.example.com/"],
            FakeRetriever({}),
            FakeLinkDiscoverer({}),
        )


def test_skips_disallowed_subdomains_and_non_http_links():
    root = "http://example.com/"
    retriever = FakeRetriever({root: RetrievalResult("root")})
    discoverer = FakeLinkDiscoverer(
        {"root": ["http://sub.example.com/page", "javascript:void(0)"]}
    )

    result = Crawler(make_policy()).crawl(
        [root], retriever, discoverer
    )

    assert result.visited_urls == (root,)
    assert result.discovered_urls == ()
    assert result.link_edges == ()


def test_records_categorized_in_scope_and_out_of_scope_references():
    root = "https://example.com/catalog/index.html"
    page = "https://example.com/catalog/page.html"
    image = "https://example.com/catalog/assets/cover.jpg"
    retriever = FakeRetriever(
        {root: RetrievalResult("root"), page: RetrievalResult("page")}
    )
    discoverer = FakeLinkDiscoverer(
        {
            "root": [
                LinkReference("page.html", category="hyperlink", follow=True),
                LinkReference("assets/cover.jpg", category="image", follow=False),
                LinkReference(
                    "https://other.example/file.pdf",
                    category="download",
                    attribute="href",
                    follow=False,
                ),
                LinkReference("mailto:info@example.com", category="email", follow=False),
            ],
            "page": [],
        }
    )

    result = Crawler(
        make_policy(allowed_url_prefixes=("https://example.com/catalog/",))
    ).crawl([root], retriever, discoverer)

    assert result.visited_urls == (root, page)
    assert result.discovered_urls == (page,)
    assert result.out_of_scope_urls == ("https://other.example/file.pdf",)
    references = {
        (item.target_url, item.category, item.scope)
        for item in result.link_references
    }
    assert (page, "hyperlink", "in_scope") in references
    assert (image, "image", "in_scope") in references
    assert ("https://other.example/file.pdf", "download", "out_of_scope") in references
    assert ("mailto:info@example.com", "email", "non_http") in references


def test_url_prefix_restricts_discovery_and_scheduling():
    root = "https://example.com/hkrw/en/index.html"
    child = "https://example.com/hkrw/en/detail.html"
    retriever = FakeRetriever(
        {root: RetrievalResult("root"), child: RetrievalResult("child")}
    )
    discoverer = FakeLinkDiscoverer(
        {
            "root": [
                "detail.html",
                "/hkrw/enough/outside.html",
                "/hkrw/zh/index.html",
                "http://example.com/hkrw/en/http.html",
            ],
            "child": [],
        }
    )
    policy = make_policy(
        allowed_url_prefixes=("HTTPS://EXAMPLE.COM:443/hkrw/en/",)
    )

    result = Crawler(policy).crawl([root], retriever, discoverer)

    assert policy.allowed_url_prefixes == ("https://example.com/hkrw/en/",)
    assert result.visited_urls == (root, child)
    assert result.discovered_urls == (child,)
    assert result.link_edges == ((root, child),)


def test_url_prefix_rejects_seed_outside_prefix():
    crawler = Crawler(
        make_policy(allowed_url_prefixes=("https://example.com/hkrw/en/",))
    )

    with pytest.raises(ValueError, match="outside"):
        crawler.crawl(
            ["https://example.com/en/index.html"],
            FakeRetriever({}),
            FakeLinkDiscoverer({}),
        )


def test_url_prefix_rejects_redirect_outside_prefix():
    root = "https://example.com/hkrw/en/start.html"
    retriever = FakeRetriever(
        {root: RetrievalResult("root", "https://example.com/en/final.html")}
    )
    discoverer = FakeLinkDiscoverer({})

    result = Crawler(
        make_policy(allowed_url_prefixes=("https://example.com/hkrw/en/",))
    ).crawl([root], retriever, discoverer)

    assert result.successful_urls == ()
    assert result.failed_urls[0].stage == "redirect"
    assert result.failed_urls[0].redirect_url == "https://example.com/en/final.html"
    assert discoverer.visited == []


def test_rejects_out_of_scope_redirect_and_records_structured_failure():
    root = "http://example.com/"
    retriever = FakeRetriever(
        {root: RetrievalResult("root", "https://elsewhere.example/")}
    )
    discoverer = FakeLinkDiscoverer({})

    result = Crawler(make_policy()).crawl(
        [root], retriever, discoverer
    )

    assert result.visited_urls == (root,)
    assert result.failed_urls[0].url == root
    assert result.failed_urls[0].stage == "redirect"
    assert result.failed_urls[0].error_type == "OutOfScopeRedirect"
    assert result.failed_urls[0].redirect_url == "https://elsewhere.example/"
    assert result.out_of_scope_urls == ("https://elsewhere.example/",)
    assert result.link_references[0].category == "redirect"
    assert result.link_references[0].scope == "out_of_scope"
    assert discoverer.visited == []


def test_resolves_links_against_in_scope_redirect_destination():
    root = "http://example.com/start"
    final = "http://example.com/redirected/page"
    target = "http://example.com/next"
    retriever = FakeRetriever(
        {root: RetrievalResult("page", final)}
    )
    discoverer = FakeLinkDiscoverer({"page": ["/next"]})

    result = Crawler(make_policy(max_pages=1)).crawl(
        [root], retriever, discoverer
    )

    assert result.link_edges == ((final, target),)
    assert result.discovered_urls == (target,)


def test_records_retrieval_and_discovery_failures():
    retrieval_url = "http://example.com/retrieval-error"
    discovery_url = "http://example.com/discovery-error"
    retriever = FakeRetriever(
        {
            retrieval_url: RuntimeError("offline"),
            discovery_url: RetrievalResult("bad-page"),
        }
    )
    discoverer = FakeLinkDiscoverer(
        {"bad-page": ValueError("cannot parse links")}
    )

    result = Crawler(make_policy()).crawl(
        [retrieval_url, discovery_url], retriever, discoverer
    )

    assert result.visited_urls == (retrieval_url, discovery_url)
    assert [(failure.url, failure.stage, failure.error_type) for failure in result.failed_urls] == [
        (retrieval_url, "retrieve", "RuntimeError"),
        (discovery_url, "discover", "ValueError"),
    ]
    assert [failure.message for failure in result.failed_urls] == [
        "offline",
        "cannot parse links",
    ]


def test_enforces_maximum_depth_but_still_reports_discovered_links():
    root = "http://example.com/"
    retriever = FakeRetriever({root: RetrievalResult("root")})
    discoverer = FakeLinkDiscoverer({"root": ["/child"]})

    result = Crawler(make_policy(max_depth=0)).crawl(
        [root], retriever, discoverer
    )

    assert result.visited_urls == (root,)
    assert result.discovered_urls == ("http://example.com/child",)
    assert result.edge_count == 1


def test_enforces_maximum_page_count():
    root = "http://example.com/"
    first = "http://example.com/a"
    second = "http://example.com/b"
    retriever = FakeRetriever(
        {url: RetrievalResult(url) for url in (root, first, second)}
    )
    discoverer = FakeLinkDiscoverer(
        {root: ["/a", "/b"], first: [], second: []}
    )

    result = Crawler(make_policy(max_pages=2)).crawl(
        [root], retriever, discoverer
    )

    assert result.visited_urls == (root, first)
    assert result.discovered_urls == (first, second)


def test_checks_elapsed_time_before_starting_more_work(monkeypatch):
    root = "http://example.com/"
    first = "http://example.com/a"
    retriever = FakeRetriever(
        {root: RetrievalResult("root"), first: RetrievalResult("first")}
    )
    discoverer = FakeLinkDiscoverer(
        {"root": ["/a", "/b"], "first": [], "second": []}
    )
    clock_values = iter((0.0, 0.0, 0.0, 0.0, 2.0, 2.0))
    monkeypatch.setattr(
        "web_scraping_crawler.crawler.time.monotonic",
        lambda: next(clock_values),
    )

    result = Crawler(make_policy(max_elapsed_time=1)).crawl(
        [root], retriever, discoverer
    )

    assert result.visited_urls == (root,)


@pytest.mark.parametrize(
    "values",
    [
        {"allowed_domains": ()},
        {"allowed_domains": ("https://example.com",)},
        {"allowed_domains": ("example.com:443",)},
        {"allowed_url_prefixes": ("https://other.example/path/",)},
        {"allowed_url_prefixes": ("https://example.com/path",)},
        {"allowed_url_prefixes": ("https://example.com/path/?q=1",)},
        {"allowed_url_prefixes": ("https://example.com/path/#section",)},
        {"max_pages": 0},
        {"max_depth": -1},
        {"max_elapsed_time": float("inf")},
        {"max_elapsed_time": 0},
        {"max_elapsed_time": "1"},
        {"max_elapsed_time": 10**1000},
    ],
)
def test_rejects_invalid_policy(values):
    with pytest.raises(ValueError):
        make_policy(**values)


def test_policy_and_results_are_immutable():
    policy = make_policy(allowed_domains=["EXAMPLE.com", "example.com"])
    result = CrawlResult((), (), (), (), ())

    assert policy.allowed_domains == ("example.com",)
    with pytest.raises(FrozenInstanceError):
        policy.max_pages = 2
    with pytest.raises(FrozenInstanceError):
        result.visited_urls = ("http://example.com/",)


def test_seed_urls_with_credentials_are_rejected():
    crawler = Crawler(make_policy())

    with pytest.raises(ValueError, match="credentials"):
        crawler.crawl(
            ["http://user@example.com/"],
            FakeRetriever({}),
            FakeLinkDiscoverer({}),
        )


def test_retriever_return_type_must_match_contract():
    root = "http://example.com/"
    retriever = FakeRetriever({root: "not a RetrievalResult"})

    result = Crawler(make_policy()).crawl(
        [root], retriever, FakeLinkDiscoverer({})
    )

    assert result.visited_urls == (root,)
    assert result.successful_urls == ()
    assert result.failed_urls[0].stage == "retrieve"
    assert result.failed_urls[0].error_type == "TypeError"
