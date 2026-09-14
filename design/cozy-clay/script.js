(() => {
  const timeNode = document.querySelector("[data-local-time]");
  const tokenToggle = document.querySelector(".token-toggle");
  const tokenDetails = document.querySelector("#token-details");
  const menuButton = document.querySelector("[data-menu-button]");
  const siteHeader = menuButton?.closest("[data-site-header]");

  if (siteHeader && menuButton) {
    siteHeader.dataset.menuReady = "true";
    siteHeader.dataset.menuOpen = "false";

    const setMenuOpen = (isOpen) => {
      siteHeader.dataset.menuOpen = String(isOpen);
      menuButton.setAttribute("aria-expanded", String(isOpen));
      menuButton.querySelector(".sr-only").textContent = isOpen
        ? "Close navigation"
        : "Open navigation";
    };

    menuButton.addEventListener("click", () => {
      setMenuOpen(siteHeader.dataset.menuOpen !== "true");
    });

    siteHeader.querySelectorAll(".nav-links a").forEach((link) => {
      link.addEventListener("click", () => setMenuOpen(false));
    });

    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") setMenuOpen(false);
    });
  }

  const updateLocalTime = () => {
    if (!timeNode) return;

    timeNode.textContent = new Intl.DateTimeFormat(undefined, {
      hour: "numeric",
      minute: "2-digit",
    }).format(new Date());
  };

  updateLocalTime();
  window.setInterval(updateLocalTime, 30_000);

  if (tokenToggle && tokenDetails) {
    tokenToggle.addEventListener("click", () => {
      const isExpanded = tokenToggle.getAttribute("aria-expanded") === "true";
      tokenToggle.setAttribute("aria-expanded", String(!isExpanded));
      tokenDetails.hidden = isExpanded;
      tokenToggle.querySelector("span").textContent = isExpanded ? "+" : "−";
      tokenToggle.firstChild.textContent = isExpanded ? "show details " : "hide details ";
    });
  }

  const revealNodes = document.querySelectorAll("[data-reveal]");
  document.documentElement.classList.add("js-reveal-ready");
  if ("IntersectionObserver" in window) {
    const revealObserver = new IntersectionObserver(
      (entries, observer) => {
        entries.forEach((entry) => {
          if (!entry.isIntersecting) return;
          entry.target.classList.add("is-visible");
          observer.unobserve(entry.target);
        });
      },
      { rootMargin: "0px 0px -8% 0px", threshold: 0.08 },
    );
    revealNodes.forEach((node) => revealObserver.observe(node));
  } else {
    revealNodes.forEach((node) => node.classList.add("is-visible"));
  }
})();
