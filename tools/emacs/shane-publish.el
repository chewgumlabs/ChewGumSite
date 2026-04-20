;;; shane-publish.el --- Publish blog posts from Org to the BBS site -*- lexical-binding: t; -*-
;;
;; One .org file per post. Emacs turns it into the three artifacts
;; tools/build.py consumes: post.toml, post.frag.html, and (for
;; experiments) a reference to site/assets/<slug>/main.js + style.css.
;;
;; Layout on disk:
;;
;;   content/blog/<slug>/
;;     post.org              ← the only file a human edits
;;     post.toml             ← generated from #+KEYWORDS here
;;     post.frag.html        ← generated from top-level Org headings
;;
;;   site/assets/<slug>/     (experiment posts only)
;;     index.html            ← dev harness; view at localhost:8765
;;     main.js               ← agent writes the experiment here
;;     style.css             ← agent writes styles here
;;     AGENT.md              ← the brief the agent reads
;;
;; Two post kinds, two sets of section rules:
;;
;;   WRITING (#+KIND: note)
;;     1. Voice window (human writes one paragraph + sentinel line)
;;     2. Metadata        (AI)
;;     3. Main Claim      (AI)
;;     4. Why It Matters  (AI)
;;     5. Supporting Observations (AI)
;;     6. Limits And Caveats      (AI)
;;     7. Related Posts   (AI)
;;     8. Preferred Citation (AI)
;;
;;   EXPERIMENT (#+KIND: experiment)
;;     1. Voice intro window (human writes AFTER the toy works)
;;     2. :experiment: window embedding site/assets/<slug>/*
;;     3. What It Is         (AI)
;;     4. Controls           (AI)
;;     5. Build Notes        (AI)
;;     6. Preferred Citation (AI)
;;
;; Commands:
;;
;;   M-x shane/new-writing
;;       Prompt for title + slug, scaffold content/blog/<slug>/post.org
;;       from writing-template.org, open it.
;;
;;   M-x shane/new-experiment
;;       Prompt for title + slug + one-line idea, scaffold BOTH
;;       content/blog/<slug>/post.org AND site/assets/<slug>/ sandbox
;;       (index.html, main.js, style.css, AGENT.md).
;;
;;   M-x shane/agent-request
;;       From an experiment's post.org buffer, prompt for a request, shell
;;       out via pi_with.sh (Control Tower launcher) to pi — the local
;;       coding-agent harness with read/bash/edit/write tools — running
;;       against the llama.cpp profile named by `shane-publish-pi-profile'
;;       (default "gemma-sd"). CWD is the sandbox dir. Output streams to
;;       *shane-agent*. `make watch' watches site/assets/ so the browser
;;       reloads on its own.
;;
;;   M-x shane/ai-draft-machine-sections
;;       Shell out to the Control Tower's ensure_(remote_)endpoint.sh
;;       script to spin up the preset's model profile on the preset's
;;       host. The script prints OPS_LOCAL_LLM_URL on stdout; Emacs POSTs
;;       the voice paragraph (and, for experiments, the sandbox source
;;       files) there with response_format=json_object, parses the JSON
;;       response, and replaces every TODO(ai) section with the drafted
;;       content. Leaves the voice section untouched.
;;
;;   M-x shane/use-llama-preset
;;       Switch which named preset is active. A preset is
;;       (:host "linux"|"mini"|"local" :profile "qwen3next"|"gemma"|…).
;;       The host names come from ~/.ssh/config; the profile names are
;;       the ones ensure_endpoint.sh understands (bonsai, coder7, gemma,
;;       qwen3next, r1distill, …). See `shane-publish-ai-presets'.
;;
;;   M-x shane/export-current-post
;;       Validate per kind (required headings, no remaining TODO markers,
;;       writing has no tangle blocks, experiment has non-empty sandbox
;;       main.js), then write post.toml + post.frag.html.
;;
;;   M-x shane/publish-current-post
;;       Export + git add/commit/push. GitHub Actions rebuilds site/.
;;
;; Setup (Doom Emacs):
;;
;;   (add-load-path! "/path/to/repo/tools/emacs")
;;   (require 'shane-publish)
;;   (add-hook 'org-mode-hook
;;             (lambda ()
;;               (when (shane-publish--current-post-dir)
;;                 (local-set-key (kbd "C-c p e") #'shane/export-current-post)
;;                 (local-set-key (kbd "C-c p d") #'shane/publish-current-post)
;;                 (local-set-key (kbd "C-c p a") #'shane/agent-request)
;;                 (local-set-key (kbd "C-c p i") #'shane/ai-draft-machine-sections)
;;                 (local-set-key (kbd "C-c p p") #'shane/use-llama-preset))))

;;; Code:

(require 'org)
(require 'ox-html)
(require 'ob-tangle)
(require 'url)
(require 'json)
(require 'cl-lib)

(defgroup shane-publish nil
  "Publish shanecurry.com blog posts from Org."
  :group 'org)

(defconst shane-publish--this-dir
  (file-name-directory (or load-file-name buffer-file-name))
  "Directory containing shane-publish.el (i.e. tools/emacs/).")

(defcustom shane-publish-ensure-endpoint-script-dir
  (expand-file-name "../../../_ChewGumAnimation/_00_Control_Tower/scripts/"
                    shane-publish--this-dir)
  "Directory containing ensure_endpoint.sh and ensure_remote_endpoint.sh
from the ChewGumAnimation Control Tower repo. The remote variant SSHs
to a host and spins up a named llama-server profile, then prints
`export OPS_LOCAL_LLM_URL=http://HOST:PORT/v1/chat/completions' on stdout.
shane-publish shells out to these scripts before each draft."
  :type 'directory :group 'shane-publish)

(defcustom shane-publish-ai-presets
  ;; Profiles picked to match what each host actually has installed in
  ;; ~/Models/.  Check with:  ssh <host> ls ~/Models/
  ;;   linux (RTX 3080, 96 GB)      → gemma-sd     (E4B target + E2B draft, SD)
  ;;   local (M4 mini Pro, 24 GB)   → gemma-sd     (same pair, M4 Pro GPU)
  ;;   mini  (M4 mini,      16 GB)  → coder7       (only coder7 is installed there)
  '((linux . (:host "linux" :profile "gemma-sd"))
    (local . (:host "local" :profile "gemma-sd"))
    (mini  . (:host "mini"  :profile "coder7")))
  "Named inference presets. Switch with `shane/use-llama-preset'.
Each entry is (NAME . PLIST) with these keys:
  :host     — SSH alias (\"linux\", \"mini\", etc. — see ~/.ssh/config) OR
              the literal string \"local\" to run against the current box.
  :profile  — model profile passed to ensure_endpoint.sh. Must be one
              recognised by the Control Tower scripts (bonsai, ternary,
              coder, coder-sd, coder7, qwen25-1.5b, gemma, gemma-sd,
              qwen3next, r1distill, qwen3.6). Determines which .gguf
              loads and therefore which port is used. Prefer the *-sd
              variants on GPU hosts for speculative-decoder speedup."
  :type '(alist :key-type symbol :value-type plist)
  :group 'shane-publish)

(defcustom shane-publish-ai-default-preset 'linux
  "Preset used at Emacs startup. `shane/use-llama-preset' changes the
runtime state; this defcustom sets the default."
  :type 'symbol :group 'shane-publish)

(defcustom shane-publish-ai-timeout 900
  "Seconds to wait for the llama-server chat response. Generous default
(15 min) because large local models are slow on cold first inference."
  :type 'integer :group 'shane-publish)

(defcustom shane-publish-ensure-endpoint-timeout 300
  "Seconds to wait for ensure_endpoint.sh to spin up / confirm a running
llama-server and print its URL. 5 min default because cold-loading a
35B-class model from disk can take over a minute just to mmap."
  :type 'integer :group 'shane-publish)

(defvar shane-publish--active-preset nil
  "Current preset symbol. Nil = use `shane-publish-ai-default-preset'.")

(defcustom shane-publish-pi-script
  (expand-file-name "../../../_ChewGumAnimation/_00_Control_Tower/scripts/pi_with.sh"
                    shane-publish--this-dir)
  "Path to pi_with.sh — the Control Tower launcher that ensures a named
llama.cpp profile is up on its port, then exec's `pi' against it. pi
itself is a local AI coding harness with read/bash/edit/write tools."
  :type 'file :group 'shane-publish)

(defcustom shane-publish-pi-profile "gemma-sd"
  "Model profile passed to pi_with.sh when `shane/agent-request' runs.
Must be one recognised by pi_with.sh:
  bonsai | ternary | coder | coder-sd | coder7 |
  qwen25-1.5b | gemma | gemma-sd.
Defaults to gemma-sd (Gemma 4 E4B + E2B draft, ~3x speedup via SD,
text-only, good for general chat/code)."
  :type '(choice (const "bonsai") (const "ternary") (const "coder")
                 (const "coder-sd") (const "coder7") (const "qwen25-1.5b")
                 (const "gemma") (const "gemma-sd") string)
  :group 'shane-publish)

(defconst shane-publish--required-sections-note
  '("Metadata" "Main Claim" "Why It Matters" "Supporting Observations"
    "Limits And Caveats" "Related Posts" "Preferred Citation")
  "Machine-section headings required for a kind=note post, in order.")

(defconst shane-publish--required-sections-experiment
  '("What It Is" "Controls" "Build Notes" "Preferred Citation")
  "Machine-section headings required for a kind=experiment post, in order.")

;;; --------------------------------------------------------------------
;;; Path helpers
;;; --------------------------------------------------------------------

(defun shane-publish--current-post-dir ()
  "If the current buffer is content/**/post.org, return its directory."
  (let ((f (buffer-file-name)))
    (when (and f (string-match-p "/content/.+/post\\.org\\'" f))
      (file-name-directory f))))

(defun shane-publish--current-post-slug ()
  "Return the slug for the current post buffer (last dir segment)."
  (let ((dir (shane-publish--current-post-dir)))
    (unless dir (user-error "Not visiting a content/**/post.org file"))
    (file-name-nondirectory (directory-file-name dir))))

(defun shane-publish--repo-root ()
  "Return the repo root for the current post buffer."
  (let ((dir (shane-publish--current-post-dir)))
    (unless dir (user-error "Not visiting a content/**/post.org file"))
    (let ((root (locate-dominating-file dir ".git")))
      (unless root (user-error "No .git found above %s" dir))
      (file-name-as-directory (expand-file-name root)))))

(defun shane-publish--repo-root-from-default ()
  "Return the repo root. shane-publish.el lives at <repo>/tools/emacs/,
so the repo is two directories up from `shane-publish--this-dir'. This
makes the new-* scaffolds work from ANY buffer (scratch, *Messages*,
a file outside the repo, etc.) — you don't have to visit a repo file
first."
  (file-name-as-directory
   (expand-file-name "../.." shane-publish--this-dir)))

(defun shane-publish--slugify (s)
  "Lowercase S, replace non-alphanumerics with '-', collapse runs, trim."
  (let ((x (downcase s)))
    (setq x (replace-regexp-in-string "[^a-z0-9]+" "-" x))
    (replace-regexp-in-string "^-+\\|-+$" "" x)))

;;; --------------------------------------------------------------------
;;; Frontmatter: read #+KEYWORDS, write post.toml
;;; --------------------------------------------------------------------

(defun shane-publish--keyword (key)
  "Return the first #+KEY: value in the current buffer, or nil."
  (org-with-wide-buffer
    (goto-char (point-min))
    (when (re-search-forward
           (concat "^[ \t]*#\\+" (regexp-quote key) ":[ \t]*\\(.*\\)$")
           nil t)
      (let ((v (string-trim (match-string 1))))
        (unless (string-empty-p v) v)))))

(defun shane-publish--toml-string (s)
  "Emit S as a double-quoted TOML string."
  (format "\"%s\""
          (replace-regexp-in-string
           "\"" "\\\\\""
           (replace-regexp-in-string "\\\\" "\\\\\\\\" s))))

(defun shane-publish--write-toml (dir)
  "Write DIR/post.toml from the current buffer's #+KEYWORDS."
  (let ((title       (shane-publish--keyword "TITLE"))
        (description (shane-publish--keyword "DESCRIPTION"))
        (canonical   (shane-publish--keyword "CANONICAL"))
        (published   (shane-publish--keyword "PUBLISHED"))
        (kind        (shane-publish--keyword "KIND"))
        (blurb       (shane-publish--keyword "BLURB")))
    (unless title     (user-error "post.org is missing #+TITLE:"))
    (unless canonical (user-error "post.org is missing #+CANONICAL:"))
    (with-temp-file (expand-file-name "post.toml" dir)
      (insert (format "title = %s\n" (shane-publish--toml-string title)))
      (when description
        (insert (format "description = %s\n" (shane-publish--toml-string description))))
      (insert (format "canonical = %s\n" (shane-publish--toml-string canonical)))
      (when published
        (unless (string-match-p "\\`[0-9]\\{4\\}-[0-9]\\{2\\}-[0-9]\\{2\\}\\'" published)
          (user-error "#+PUBLISHED must be YYYY-MM-DD, got: %s" published))
        (insert (format "published = %s\n" published)))
      (when kind
        (insert (format "kind = %s\n" (shane-publish--toml-string kind))))
      (when blurb
        (insert (format "blurb = %s\n" (shane-publish--toml-string blurb)))))))

;;; --------------------------------------------------------------------
;;; Body export: each level-1 heading → one <section class="window">
;;; --------------------------------------------------------------------

(defun shane-publish--escape-html (s)
  (replace-regexp-in-string
   "\"" "&quot;"
   (replace-regexp-in-string
    "<" "&lt;"
    (replace-regexp-in-string
     ">" "&gt;"
     (replace-regexp-in-string "&" "&amp;" s)))))

(defun shane-publish--org-string-to-html (s)
  "Export Org source string S to a body-only HTML fragment."
  (let ((org-export-with-toc nil)
        (org-export-with-section-numbers nil)
        (org-export-with-sub-superscripts nil)
        (org-html-htmlize-output-type 'css)
        (org-html-doctype "html5")
        (org-html-html5-fancy nil)
        (org-html-container-element "div")
        (org-html-text-markup-alist
         '((bold          . "<strong>%s</strong>")
           (code          . "<code>%s</code>")
           (italic        . "<em>%s</em>")
           (strike-through . "<del>%s</del>")
           (underline     . "<span class=\"underline\">%s</span>")
           (verbatim      . "<code>%s</code>"))))
    (with-temp-buffer
      (insert s)
      (org-mode)
      (org-export-as 'html nil nil t
                     '(:with-toc nil :section-numbers nil)))))

(defun shane-publish--strip-outline-wrappers (html)
  "Strip Org's outline <div> wrappers and per-heading <h2> anchors."
  (let ((s html))
    (setq s (replace-regexp-in-string
             "<div id=\"outline-container-[^\"]*\"[^>]*>" "" s))
    (setq s (replace-regexp-in-string
             "<div class=\"outline-text-[^\"]*\"[^>]*>" "" s))
    (setq s (replace-regexp-in-string
             "<h2[^>]*>[^<]*</h2>" "" s))
    s))

(defun shane-publish--collect-windows ()
  "Parse buffer, return list of (TITLE EXPERIMENT BODY-ORG) tuples."
  (let* ((ast (org-element-parse-buffer))
         (level1 (org-element-map ast 'headline
                   (lambda (h)
                     (when (= 1 (org-element-property :level h)) h)))))
    (mapcar
     (lambda (h)
       (let* ((title (org-element-property :raw-value h))
              (tags (or (org-element-property :tags h) '()))
              (beg (org-element-property :contents-begin h))
              (end (org-element-property :contents-end h))
              (body-org (if (and beg end)
                            (buffer-substring-no-properties beg end)
                          "")))
         (list title (member "experiment" tags) body-org)))
     level1)))

(defun shane-publish--render-window (window)
  (let* ((title (nth 0 window))
         (experiment (nth 1 window))
         (body-org (nth 2 window))
         (body-html (shane-publish--strip-outline-wrappers
                     (shane-publish--org-string-to-html body-org))))
    (format
     (concat "      <section class=\"window\" data-title=\"%s\"%s>\n"
             "        <div class=\"window-content\">\n"
             "%s"
             "        </div>\n"
             "      </section>\n")
     (shane-publish--escape-html title)
     (if experiment " data-experiment" "")
     body-html)))

(defun shane-publish--write-frag-html (dir)
  (let ((windows (shane-publish--collect-windows)))
    (unless windows
      (user-error "post.org has no top-level `* Heading' windows"))
    (let ((rendered (mapconcat #'shane-publish--render-window windows "\n")))
      (with-temp-file (expand-file-name "post.frag.html" dir)
        (insert rendered)))))

;;; --------------------------------------------------------------------
;;; Validation (runs before export writes anything)
;;; --------------------------------------------------------------------

(defun shane-publish--collect-level1-heading-names ()
  "Return a list of (NAME . TAGS) pairs in document order."
  (let* ((ast (org-element-parse-buffer 'headline)))
    (org-element-map ast 'headline
      (lambda (h)
        (when (= 1 (org-element-property :level h))
          (cons (org-element-property :raw-value h)
                (or (org-element-property :tags h) '())))))))

(defun shane-publish--count-tangle-blocks ()
  "Return the number of #+BEGIN_SRC blocks that have a :tangle header."
  (let ((ast (org-element-parse-buffer 'element))
        (count 0))
    (org-element-map ast 'src-block
      (lambda (b)
        (let* ((params (or (org-element-property :parameters b) ""))
               (header (or (org-element-property :header b) '()))
               (joined (concat params " " (mapconcat #'identity header " "))))
          (when (string-match-p ":tangle[ \t]+[^ \t]" joined)
            (cl-incf count)))))
    count))

(defun shane-publish--find-todo-marker ()
  "Return (LINE . MARKER) of the first TODO(ai|human) marker, or nil."
  (org-with-wide-buffer
    (goto-char (point-min))
    (when (re-search-forward "TODO(\\(ai\\|human\\))" nil t)
      (cons (line-number-at-pos (match-beginning 0))
            (match-string 0)))))

(defun shane-publish--validate-kind (kind)
  (unless (member kind '("note" "experiment"))
    (user-error "#+KIND must be \"note\" or \"experiment\", got %S" kind)))

(defun shane-publish--validate-no-todos ()
  (when-let ((hit (shane-publish--find-todo-marker)))
    (user-error "Unfilled %s marker on line %d — draft or write before export"
                (cdr hit) (car hit))))

(defun shane-publish--validate-required-keywords ()
  (dolist (k '("TITLE" "CANONICAL" "PUBLISHED" "DESCRIPTION" "BLURB" "KIND"))
    (let ((v (shane-publish--keyword k)))
      (when (or (null v) (string-match-p "TODO(" v))
        (user-error "Keyword #+%s: is missing or still a TODO placeholder" k)))))

(defun shane-publish--validate-headings (kind)
  (let* ((headings (shane-publish--collect-level1-heading-names))
         (names (mapcar #'car headings)))
    (pcase kind
      ("note"
       (unless (>= (length headings) (1+ (length shane-publish--required-sections-note)))
         (user-error "Writing post needs a voice heading + %d machine sections, found %d headings"
                     (length shane-publish--required-sections-note) (length headings)))
       ;; positions 1..7 after voice must be exact names in order
       (let ((expected shane-publish--required-sections-note)
             (got (cdr names)))
         (cl-loop for want in expected
                  for have in got
                  unless (equal want have)
                  do (user-error "Writing post: expected heading %S, got %S" want have))))
      ("experiment"
       (unless (>= (length headings) (+ 2 (length shane-publish--required-sections-experiment)))
         (user-error "Experiment post needs voice + prototype + %d machine sections, found %d headings"
                     (length shane-publish--required-sections-experiment) (length headings)))
       ;; position 2 must have :experiment: tag
       (let ((second (nth 1 headings)))
         (unless (member "experiment" (cdr second))
           (user-error "Experiment post: second heading %S must have the :experiment: tag" (car second))))
       ;; positions 3..6 must be exact names in order
       (let ((expected shane-publish--required-sections-experiment)
             (got (nthcdr 2 names)))
         (cl-loop for want in expected
                  for have in got
                  unless (equal want have)
                  do (user-error "Experiment post: expected heading %S, got %S" want have)))))))

(defun shane-publish--validate-kind-side-files (kind slug repo-root)
  (pcase kind
    ("note"
     (let ((n (shane-publish--count-tangle-blocks)))
       (when (> n 0)
         (user-error "Writing posts are prose only. Found %d :tangle block(s). Remove them, or change #+KIND: to experiment" n))))
    ("experiment"
     (let* ((main (expand-file-name (format "site/assets/%s/main.js" slug) repo-root)))
       (unless (file-exists-p main)
         (user-error "Experiment post missing sandbox file: %s"
                     (file-relative-name main repo-root)))
       (when (zerop (nth 7 (file-attributes main)))
         (user-error "Experiment sandbox main.js is empty: %s"
                     (file-relative-name main repo-root)))))))

(defun shane-publish--validate-all ()
  "Run all pre-export validations. Raises `user-error' on failure."
  (let* ((kind (shane-publish--keyword "KIND"))
         (slug (shane-publish--current-post-slug))
         (repo (shane-publish--repo-root)))
    (shane-publish--validate-kind kind)
    (shane-publish--validate-required-keywords)
    (shane-publish--validate-no-todos)
    (shane-publish--validate-headings kind)
    (shane-publish--validate-kind-side-files kind slug repo)))

;;; --------------------------------------------------------------------
;;; Scaffolding: new-writing, new-experiment
;;; --------------------------------------------------------------------

(defun shane-publish--substitute (title slug published idea)
  "In current buffer, replace <TITLE>/<SLUG>/<PUBLISHED>/<IDEA> literals."
  (dolist (pair `(("<TITLE>"     . ,title)
                  ("<SLUG>"      . ,slug)
                  ("<PUBLISHED>" . ,published)
                  ("<IDEA>"      . ,(or idea ""))))
    (goto-char (point-min))
    (while (search-forward (car pair) nil t)
      (replace-match (cdr pair) t t))))

(defun shane-publish--copy-template-file (src dst title slug published idea)
  (with-temp-file dst
    (insert-file-contents src)
    (shane-publish--substitute title slug published idea)))

(defun shane-publish--scaffold-post-org (template-name title slug repo-root)
  "Write content/blog/<slug>/post.org from TEMPLATE-NAME. Returns the path."
  (let* ((post-dir (expand-file-name (format "content/blog/%s/" slug) repo-root))
         (post-file (expand-file-name "post.org" post-dir))
         (src (expand-file-name template-name shane-publish--this-dir))
         (today (format-time-string "%Y-%m-%d")))
    (unless (file-exists-p src)
      (user-error "Template not found: %s" src))
    (when (file-exists-p post-dir)
      (user-error "Post directory already exists: %s" post-dir))
    (make-directory post-dir t)
    (shane-publish--copy-template-file src post-file title slug today nil)
    post-file))

(defun shane-publish--scaffold-sandbox (slug title idea repo-root)
  "Copy sandbox-template/ to site/assets/<slug>/ with substitutions."
  (let* ((sandbox-dir (expand-file-name (format "site/assets/%s/" slug) repo-root))
         (template-dir (expand-file-name "sandbox-template/" shane-publish--this-dir))
         (today (format-time-string "%Y-%m-%d")))
    (unless (file-directory-p template-dir)
      (user-error "Sandbox template dir missing: %s" template-dir))
    (when (file-exists-p sandbox-dir)
      (user-error "Sandbox already exists: %s" sandbox-dir))
    (make-directory sandbox-dir t)
    (dolist (f (directory-files template-dir nil "\\`[^.]" t))
      (let ((src (expand-file-name f template-dir))
            (dst (expand-file-name f sandbox-dir)))
        (when (file-regular-p src)
          (shane-publish--copy-template-file src dst title slug today idea))))
    sandbox-dir))

(defun shane-publish--prompt-slug (title)
  (let ((default (shane-publish--slugify title)))
    (let ((s (read-string (format "Slug [%s]: " default) nil nil default)))
      (if (string-empty-p s)
          default
        (shane-publish--slugify s)))))

;;;###autoload
(defun shane/new-writing ()
  "Scaffold a new writing (kind=note) post from writing-template.org."
  (interactive)
  (let* ((repo (shane-publish--repo-root-from-default))
         (title (read-string "Title: "))
         (_ (when (string-empty-p title) (user-error "Title cannot be empty")))
         (slug (shane-publish--prompt-slug title))
         (post-file (shane-publish--scaffold-post-org
                     "writing-template.org" title slug repo)))
    (find-file post-file)
    (message "Scaffolded %s.  Write the voice paragraph, then M-x shane/ai-draft-machine-sections."
             (file-relative-name post-file repo))))

;;;###autoload
(defun shane/new-experiment ()
  "Scaffold a new experiment (kind=experiment) post plus a sandbox dir."
  (interactive)
  (let* ((repo (shane-publish--repo-root-from-default))
         (title (read-string "Title: "))
         (_ (when (string-empty-p title) (user-error "Title cannot be empty")))
         (idea (read-string "One-line idea for the agent brief: "))
         (slug (shane-publish--prompt-slug title))
         (post-file (shane-publish--scaffold-post-org
                     "experiment-template.org" title slug repo))
         (sandbox (shane-publish--scaffold-sandbox slug title idea repo)))
    (find-file post-file)
    (message "Scaffolded:
  %s
  %s
Start `make watch', view http://localhost:8765/assets/%s/ , then M-x shane/agent-request."
             (file-relative-name post-file repo)
             (file-relative-name sandbox repo)
             slug)))

;;; --------------------------------------------------------------------
;;; Headless agent invocation (for experiment sandboxes)
;;; --------------------------------------------------------------------

;;;###autoload
(defun shane/agent-request (request)
  "Send REQUEST to pi (the local coding-agent harness) running in
site/assets/<slug>/ for the current post. pi_with.sh spins up the
llama.cpp profile named by `shane-publish-pi-profile' if not already
up, then exec's pi against it. Output streams to *shane-agent*.
Browser auto-reloads via `make watch'."
  (interactive (list (read-string "Agent request: ")))
  (when (string-empty-p request)
    (user-error "Request cannot be empty"))
  (let* ((kind (shane-publish--keyword "KIND")))
    (unless (equal kind "experiment")
      (user-error "shane/agent-request only makes sense in an experiment post (#+KIND: experiment)")))
  (unless (file-exists-p shane-publish-pi-script)
    (user-error "pi_with.sh not found at %s (set `shane-publish-pi-script')"
                shane-publish-pi-script))
  (let* ((slug (shane-publish--current-post-slug))
         (repo (shane-publish--repo-root))
         (sandbox (expand-file-name (format "site/assets/%s/" slug) repo))
         (cmd (format "bash %s %s -p %s"
                      (shell-quote-argument shane-publish-pi-script)
                      (shell-quote-argument shane-publish-pi-profile)
                      (shell-quote-argument request)))
         (buf (get-buffer-create "*shane-agent*")))
    (unless (file-directory-p sandbox)
      (user-error "No sandbox at %s — scaffold was incomplete" sandbox))
    (with-current-buffer buf
      (let ((inhibit-read-only t))
        (goto-char (point-max))
        (insert (format "\n\n=== %s ===\n$ cd %s\n$ %s\n\n"
                        (format-time-string "%H:%M:%S")
                        (file-relative-name sandbox repo)
                        cmd))))
    (display-buffer buf)
    (let ((default-directory sandbox))
      (make-process
       :name "shane-agent"
       :buffer buf
       :command (list shell-file-name shell-command-switch cmd)
       :sentinel (lambda (_p event)
                   (when (buffer-live-p buf)
                     (with-current-buffer buf
                       (goto-char (point-max))
                       (insert (format "\n[agent %s]\n" (string-trim event))))))))
    (message "Agent launched in %s. Output → *shane-agent*."
             (file-relative-name sandbox repo))))

;;; --------------------------------------------------------------------
;;; LLM client: shell out to ChewGumAnimation's Control Tower
;;; ensure_endpoint.sh / ensure_remote_endpoint.sh to spin up a named
;;; llama.cpp profile on a named host, parse the OPS_LOCAL_LLM_URL line
;;; from stdout, then POST an OpenAI-compatible chat request with
;;; response_format=json_object to force JSON output.
;;; --------------------------------------------------------------------

(defun shane-publish--read-template (relpath)
  "Read a text file under tools/emacs/ (relative path)."
  (let ((f (expand-file-name relpath shane-publish--this-dir)))
    (unless (file-exists-p f)
      (user-error "Missing template: %s" f))
    (with-temp-buffer
      (insert-file-contents f)
      (buffer-string))))

(defun shane-publish--extract-voice-section ()
  "Return the body text of the first top-level heading (voice window)."
  (save-excursion
    (goto-char (point-min))
    (unless (re-search-forward "^\\* " nil t)
      (user-error "No top-level heading found"))
    (let* ((beg (line-beginning-position 2))
           (end (if (re-search-forward "^\\* " nil t)
                    (match-beginning 0)
                  (point-max))))
      (string-trim (buffer-substring-no-properties beg end)))))

(defun shane-publish--collect-keywords-alist ()
  "Return an alist of keyword values needed by the LLM prompt."
  `((title      . ,(or (shane-publish--keyword "TITLE") ""))
    (canonical  . ,(or (shane-publish--keyword "CANONICAL") ""))
    (published  . ,(or (shane-publish--keyword "PUBLISHED") ""))
    (kind       . ,(or (shane-publish--keyword "KIND") ""))))

(defun shane-publish--read-sandbox-files (slug)
  "Return a labeled concat of sandbox files (for the experiment prompt)."
  (let* ((repo (shane-publish--repo-root))
         (dir (expand-file-name (format "site/assets/%s/" slug) repo))
         (parts '()))
    (dolist (name '("AGENT.md" "main.js" "style.css" "index.html"))
      (let ((p (expand-file-name name dir)))
        (when (file-exists-p p)
          (push (format "=== %s ===\n%s\n"
                        name
                        (with-temp-buffer
                          (insert-file-contents p)
                          (buffer-string)))
                parts))))
    (string-join (nreverse parts) "\n")))

(defun shane-publish--build-user-message (kind voice meta extra)
  "Compose the user message sent to the LLM."
  (let* ((title     (alist-get 'title meta))
         (canonical (alist-get 'canonical meta))
         (published (alist-get 'published meta)))
    (concat
     (format "POST KIND: %s\n" kind)
     (format "TITLE: %s\n" title)
     (format "CANONICAL: %s\n" canonical)
     (format "PUBLISHED: %s\n\n" published)
     "VOICE PARAGRAPH (source of truth):\n"
     voice
     "\n"
     (when (and extra (not (string-empty-p extra)))
       (concat "\nSANDBOX SOURCE FILES:\n" extra))
     "\nRespond with the JSON object specified in the system prompt. No commentary.")))

(defun shane-publish--current-preset-name ()
  "Return the symbol naming the active preset."
  (or shane-publish--active-preset shane-publish-ai-default-preset))

(defun shane-publish--current-preset ()
  "Return the plist for the active preset. Raise user-error if unknown."
  (let* ((name (shane-publish--current-preset-name))
         (plist (alist-get name shane-publish-ai-presets)))
    (unless plist
      (user-error "No preset named %s in `shane-publish-ai-presets'" name))
    plist))

(defun shane-publish--ensure-endpoint-script (host)
  "Return absolute path to the right ensure_endpoint script for HOST.
`local' uses the in-place script; any other host uses the SSH wrapper."
  (let* ((dir (file-name-as-directory shane-publish-ensure-endpoint-script-dir))
         (name (if (equal host "local")
                   "ensure_endpoint.sh"
                 "ensure_remote_endpoint.sh"))
         (path (expand-file-name name dir)))
    (unless (file-exists-p path)
      (user-error "Missing endpoint script: %s (set `shane-publish-ensure-endpoint-script-dir')"
                  path))
    path))

(defun shane-publish--parse-endpoint-url (stdout)
  "Pull the OPS_LOCAL_LLM_URL value out of ensure_endpoint.sh stdout."
  (when (string-match
         "^[[:space:]]*export[[:space:]]+OPS_LOCAL_LLM_URL=\\(.+\\)$"
         stdout)
    (let ((raw (string-trim (match-string 1 stdout))))
      ;; Strip quotes if present.
      (cond
       ((and (> (length raw) 1)
             (= (aref raw 0) ?')
             (= (aref raw (1- (length raw))) ?'))
        (substring raw 1 -1))
       ((and (> (length raw) 1)
             (= (aref raw 0) ?\")
             (= (aref raw (1- (length raw))) ?\"))
        (substring raw 1 -1))
       (t raw)))))

(defun shane-publish--ensure-endpoint (preset)
  "Run ensure_(remote_)endpoint.sh for PRESET, return the resolved URL.
Surfaces the script's stderr into *shane-publish-ai* on failure."
  (let* ((host    (or (plist-get preset :host)
                      (user-error "Preset missing :host")))
         (profile (or (plist-get preset :profile)
                      (user-error "Preset missing :profile")))
         (script  (shane-publish--ensure-endpoint-script host))
         ;; `call-process' wants a FILE path for stderr, not a buffer.
         (stderr-file (make-temp-file "shane-publish-ensure-" nil ".log"))
         (stdout-buf (generate-new-buffer " *shane-ensure-stdout*"))
         (cmd (if (equal host "local")
                  (list "bash" script profile)
                (list "bash" script host profile)))
         (exit-code
          (let ((default-directory (file-name-as-directory
                                    (or (file-name-directory script) "."))))
            (with-timeout
                (shane-publish-ensure-endpoint-timeout
                 (when (buffer-live-p stdout-buf) (kill-buffer stdout-buf))
                 (when (file-exists-p stderr-file) (delete-file stderr-file))
                 (user-error "ensure_endpoint.sh timed out after %ds"
                             shane-publish-ensure-endpoint-timeout))
              (apply #'call-process (car cmd) nil
                     (list stdout-buf stderr-file)
                     nil (cdr cmd)))))
         (stdout (with-current-buffer stdout-buf
                   (prog1 (buffer-string) (kill-buffer stdout-buf))))
         (stderr (when (file-exists-p stderr-file)
                   (prog1 (with-temp-buffer
                            (insert-file-contents stderr-file)
                            (buffer-string))
                     (delete-file stderr-file)))))
    (unless (zerop exit-code)
      (shane-publish--dump-raw
       (concat "=== stderr ===\n" (or stderr "")
               "\n=== stdout ===\n" stdout))
      (user-error "ensure_endpoint.sh %s %s exited %d — see *shane-publish-ai*"
                  host profile exit-code))
    (or (shane-publish--parse-endpoint-url stdout)
        (progn
          (shane-publish--dump-raw
           (concat "=== stderr ===\n" (or stderr "")
                   "\n=== stdout ===\n" stdout))
          (user-error "ensure_endpoint.sh %s %s did not emit OPS_LOCAL_LLM_URL — see *shane-publish-ai*"
                      host profile)))))

(defun shane-publish--llama-chat (system-prompt user-message)
  "Resolve endpoint via ensure_endpoint.sh, POST an OpenAI-compat chat
request, return the `content' string (which itself is JSON because
`response_format' is forced to `json_object')."
  (let* ((preset-name (shane-publish--current-preset-name))
         (preset      (shane-publish--current-preset))
         (profile     (plist-get preset :profile))
         (_ (message "Ensuring endpoint for %s (%s@%s)…"
                     preset-name profile (plist-get preset :host)))
         (endpoint    (shane-publish--ensure-endpoint preset)))
    (message "Drafting via %s (endpoint: %s)…" preset-name endpoint)
    (let* ((payload (json-serialize
                     `((model . ,profile)
                       (messages . [((role . "system")
                                     (content . ,system-prompt))
                                    ((role . "user")
                                     (content . ,user-message))])
                       (response_format . ((type . "json_object")))
                       (stream . :false)
                       (temperature . 0.4))))
           (url-request-method "POST")
           (url-request-extra-headers '(("Content-Type" . "application/json")))
           (url-request-data (encode-coding-string payload 'utf-8))
           (buf (condition-case err
                    (let ((url-show-status nil))
                      (with-timeout (shane-publish-ai-timeout
                                     (user-error "llama-server request timed out after %ds"
                                                 shane-publish-ai-timeout))
                        (url-retrieve-synchronously endpoint t t)))
                  (file-error
                   (user-error "llama-server at %s unreachable after ensure_endpoint: %s"
                               endpoint (error-message-string err))))))
      (unless buf
        (user-error "llama-server at %s returned no response" endpoint))
      (with-current-buffer buf
        (goto-char (point-min))
        (let ((status-line (buffer-substring-no-properties
                            (point) (line-end-position))))
          (unless (string-match-p "\\`HTTP/[0-9.]+ 200" status-line)
            (let ((raw (buffer-string)))
              (kill-buffer buf)
              (shane-publish--dump-raw raw)
              (user-error "llama-server returned: %s" status-line))))
        (re-search-forward "\n\n" nil t)
        (let* ((body (buffer-substring-no-properties (point) (point-max)))
               (parsed (condition-case err
                           (json-parse-string body :object-type 'hash-table
                                              :array-type 'list
                                              :false-object :false
                                              :null-object nil)
                         (json-parse-error
                          (shane-publish--dump-raw body)
                          (user-error "llama-server response was not valid JSON (raw in *shane-publish-ai*): %s"
                                      (error-message-string err))))))
          (kill-buffer buf)
          (let* ((choices (gethash "choices" parsed))
                 (first   (and (listp choices) (car choices)))
                 (message (and first (gethash "message" first)))
                 (content (and message (gethash "content" message))))
            (unless content
              (shane-publish--dump-raw body)
              (user-error "llama-server response missing choices[0].message.content (raw in *shane-publish-ai*)"))
            content))))))

;;;###autoload
(defun shane/use-llama-preset (preset)
  "Switch the active llama-server preset.  The next
`shane/ai-draft-machine-sections' call will shell out to
ensure_endpoint.sh for the new preset before POSTing."
  (interactive
   (list (intern
          (completing-read
           "llama preset: "
           (mapcar (lambda (p) (symbol-name (car p))) shane-publish-ai-presets)
           nil t nil nil
           (symbol-name (shane-publish--current-preset-name))))))
  (unless (assq preset shane-publish-ai-presets)
    (user-error "No preset named %s in `shane-publish-ai-presets'" preset))
  (setq shane-publish--active-preset preset)
  (let ((p (alist-get preset shane-publish-ai-presets)))
    (message "Active llama preset: %s  (%s@%s)"
             preset (plist-get p :profile) (plist-get p :host))))

(defun shane-publish--dump-raw (s)
  (let ((buf (get-buffer-create "*shane-publish-ai*")))
    (with-current-buffer buf
      (erase-buffer)
      (insert s))
    (display-buffer buf)))

(defun shane-publish--parse-sections-json (json-str kind)
  "Parse JSON-STR and validate required keys for KIND."
  (let* ((parsed (condition-case err
                     (json-parse-string json-str :object-type 'hash-table
                                        :array-type 'list
                                        :false-object :false
                                        :null-object nil)
                   (json-parse-error
                    (shane-publish--dump-raw json-str)
                    (user-error "LLM section JSON malformed: %s (raw in *shane-publish-ai*)"
                                (error-message-string err)))))
         (required (pcase kind
                     ("note"       '("description" "blurb" "metadata"
                                     "main_claim" "why_it_matters"
                                     "supporting_observations"
                                     "limits_and_caveats" "related_posts" "citation"))
                     ("experiment" '("description" "blurb" "what_it_is"
                                     "controls" "build_notes" "citation")))))
    (dolist (k required)
      (unless (gethash k parsed)
        (shane-publish--dump-raw json-str)
        (user-error "LLM response missing required key: %s (raw in *shane-publish-ai*)" k)))
    parsed))

;;; --------------------------------------------------------------------
;;; Render machine sections from parsed JSON
;;; --------------------------------------------------------------------

(defconst shane-publish--month-names
  ["January" "February" "March" "April" "May" "June"
   "July" "August" "September" "October" "November" "December"])

(defun shane-publish--format-pretty-date (ymd)
  "2026-04-19 → \"April 19, 2026\"."
  (if (and ymd (string-match "\\`\\([0-9]\\{4\\}\\)-\\([0-9]\\{2\\}\\)-\\([0-9]\\{2\\}\\)\\'" ymd))
      (let* ((year  (string-to-number (match-string 1 ymd)))
             (month (string-to-number (match-string 2 ymd)))
             (day   (string-to-number (match-string 3 ymd))))
        (format "%s %d, %d"
                (aref shane-publish--month-names (1- month))
                day year))
    (or ymd "")))

(defun shane-publish--render-metadata (meta canonical published)
  (let ((pretty (shane-publish--format-pretty-date published))
        (tags (gethash "tags" meta)))
    (concat
     "#+BEGIN_EXPORT html\n"
     "<dl class=\"meta-grid\">\n"
     "  <dt>Type</dt>\n"
     (format "  <dd>%s</dd>\n" (or (gethash "type" meta) "Blog post"))
     "  <dt>Status</dt>\n"
     (format "  <dd>%s</dd>\n" (or (gethash "status" meta) "Working Note"))
     "  <dt>Published</dt>\n"
     (format "  <dd>%s</dd>\n" pretty)
     "  <dt>Updated</dt>\n"
     (format "  <dd>%s</dd>\n" pretty)
     "  <dt>Source session</dt>\n"
     (format "  <dd>%s</dd>\n" (or (gethash "source_session" meta) "None yet"))
     "  <dt>Canonical URL</dt>\n"
     (format "  <dd><a href=\"%s\">%s</a></dd>\n" canonical canonical)
     "  <dt>Tags</dt>\n"
     (format "  <dd>%s</dd>\n"
             (if (and tags (listp tags) tags)
                 (string-join tags ", ")
               "None yet"))
     "  <dt>Related project</dt>\n"
     (format "  <dd>%s</dd>\n" (or (gethash "related_project" meta) "None yet"))
     "  <dt>Related repo</dt>\n"
     (format "  <dd>%s</dd>\n" (or (gethash "related_repo" meta) "None yet"))
     "  <dt>External links</dt>\n"
     (format "  <dd>%s</dd>\n" (or (gethash "external_links" meta) "None yet"))
     "  <dt>Confidence</dt>\n"
     (format "  <dd>%s</dd>\n" (or (gethash "confidence" meta) "Observational"))
     "</dl>\n"
     "#+END_EXPORT")))

(defun shane-publish--render-supporting-observations (obj)
  (let ((prose    (or (gethash "prose" obj) ""))
        (quote    (or (gethash "quote" obj) ""))
        (followup (or (gethash "followup" obj) "")))
    (string-join
     (delq nil
           (list (and (not (string-empty-p prose)) prose)
                 (and (not (string-empty-p quote))
                      (format "#+BEGIN_QUOTE\n%s\n#+END_QUOTE" quote))
                 (and (not (string-empty-p followup)) followup)))
     "\n\n")))

(defun shane-publish--render-related-posts (items)
  (if (and (listp items) items)
      (mapconcat
       (lambda (it)
         (format "- [[%s][%s]]"
                 (or (gethash "url" it) "/blog/")
                 (or (gethash "title" it) "(untitled)")))
       items "\n")
    "None yet"))

(defun shane-publish--render-controls (items)
  (if (and (listp items) items)
      (mapconcat (lambda (s) (format "- %s" s)) items "\n")
    "None."))

(defun shane-publish--replace-heading-body (heading-name new-body)
  "Replace the body of the first level-1 heading named HEADING-NAME."
  (save-excursion
    (goto-char (point-min))
    (let ((pat (format "^\\* %s[ \t]*$" (regexp-quote heading-name))))
      (unless (re-search-forward pat nil t)
        (user-error "Heading not found: * %s" heading-name))
      (let* ((body-beg (line-beginning-position 2))
             (body-end (if (re-search-forward "^\\* " nil t)
                           (match-beginning 0)
                         (point-max))))
        (delete-region body-beg body-end)
        (goto-char body-beg)
        (insert new-body)
        (unless (bolp) (insert "\n"))
        (unless (looking-at "\n") (insert "\n"))))))

(defun shane-publish--replace-keyword (key new-value)
  "Replace the value of #+KEY: if currently `TODO(ai)' or empty."
  (save-excursion
    (goto-char (point-min))
    (when (re-search-forward
           (format "^\\(#\\+%s:[ \t]*\\)\\(.*\\)$" (regexp-quote key))
           nil t)
      (let ((cur (string-trim (match-string 2))))
        (when (or (string-empty-p cur) (string-match-p "\\`TODO(ai)\\'" cur))
          (replace-match (format "\\1%s" new-value) t nil))))))

(defun shane-publish--replace-machine-sections (parsed kind)
  "Walk PARSED JSON and replace each machine-section body + keywords."
  (let ((canonical (shane-publish--keyword "CANONICAL"))
        (published (shane-publish--keyword "PUBLISHED")))
    (shane-publish--replace-keyword "DESCRIPTION" (or (gethash "description" parsed) ""))
    (shane-publish--replace-keyword "BLURB"       (or (gethash "blurb"       parsed) ""))
    (pcase kind
      ("note"
       (shane-publish--replace-heading-body
        "Metadata" (shane-publish--render-metadata
                    (gethash "metadata" parsed) canonical published))
       (shane-publish--replace-heading-body
        "Main Claim" (or (gethash "main_claim" parsed) ""))
       (shane-publish--replace-heading-body
        "Why It Matters" (or (gethash "why_it_matters" parsed) ""))
       (shane-publish--replace-heading-body
        "Supporting Observations"
        (shane-publish--render-supporting-observations
         (gethash "supporting_observations" parsed)))
       (shane-publish--replace-heading-body
        "Limits And Caveats" (or (gethash "limits_and_caveats" parsed) ""))
       (shane-publish--replace-heading-body
        "Related Posts"
        (shane-publish--render-related-posts (gethash "related_posts" parsed)))
       (shane-publish--replace-heading-body
        "Preferred Citation" (or (gethash "citation" parsed) "")))
      ("experiment"
       (shane-publish--replace-heading-body
        "What It Is" (or (gethash "what_it_is" parsed) ""))
       (shane-publish--replace-heading-body
        "Controls"
        (shane-publish--render-controls (gethash "controls" parsed)))
       (shane-publish--replace-heading-body
        "Build Notes" (or (gethash "build_notes" parsed) ""))
       (shane-publish--replace-heading-body
        "Preferred Citation" (or (gethash "citation" parsed) ""))))))

;;;###autoload
(defun shane/ai-draft-machine-sections ()
  "Read voice + (for experiments) sandbox files, POST to local LLM,
replace every TODO(ai) section with the returned content."
  (interactive)
  (let ((dir (shane-publish--current-post-dir)))
    (unless dir (user-error "Not visiting a content/**/post.org file")))
  (save-buffer)
  (let* ((kind (or (shane-publish--keyword "KIND")
                   (user-error "post.org missing #+KIND:")))
         (_    (shane-publish--validate-kind kind))
         (slug (shane-publish--current-post-slug))
         (prompt-file (pcase kind
                        ("note"       "prompts/writing-machine-sections.md")
                        ("experiment" "prompts/experiment-machine-sections.md")))
         (system-prompt (shane-publish--read-template prompt-file))
         (voice (shane-publish--extract-voice-section))
         (meta  (shane-publish--collect-keywords-alist))
         (extra (when (equal kind "experiment")
                  (shane-publish--read-sandbox-files slug)))
         (user-msg (shane-publish--build-user-message kind voice meta extra))
         (content (shane-publish--llama-chat system-prompt user-msg))
         (parsed (shane-publish--parse-sections-json content kind)))
    (shane-publish--replace-machine-sections parsed kind)
    (save-buffer)
    (message "Machine sections drafted. Review before publishing.")))

;;; --------------------------------------------------------------------
;;; Top-level commands: export, publish
;;; --------------------------------------------------------------------

;;;###autoload
(defun shane/export-current-post ()
  "Validate + tangle + write post.toml + write post.frag.html."
  (interactive)
  (let ((dir (shane-publish--current-post-dir)))
    (unless dir (user-error "Not visiting a content/**/post.org file"))
    (save-buffer)
    (shane-publish--validate-all)
    (let ((org-confirm-babel-evaluate nil))
      (org-babel-tangle))
    (shane-publish--write-toml dir)
    (shane-publish--write-frag-html dir)
    (message "Exported %s (post.toml + post.frag.html)"
             (file-relative-name dir (shane-publish--repo-root)))))

;;;###autoload
(defun shane/publish-current-post (commit-msg)
  "Export, then commit `content/' + `site/assets/' and push to origin.
GitHub Actions rebuilds site/ and deploys."
  (interactive
   (list (read-string "Commit message: "
                      (format "%s: update"
                              (file-name-nondirectory
                               (directory-file-name
                                (shane-publish--current-post-dir)))))))
  (shane/export-current-post)
  (let ((default-directory (shane-publish--repo-root)))
    (let ((git-output
           (shell-command-to-string
            (format "git add content/ site/assets/ && git commit -m %s && git push 2>&1"
                    (shell-quote-argument commit-msg)))))
      (with-current-buffer (get-buffer-create "*shane-publish*")
        (erase-buffer)
        (insert git-output)
        (display-buffer (current-buffer)))
      (message "Pushed %s — watch: https://github.com/chewgumplaygames/shanecurryblog/actions"
               commit-msg))))

(provide 'shane-publish)
;;; shane-publish.el ends here
