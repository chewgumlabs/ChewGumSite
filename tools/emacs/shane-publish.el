;;; shane-publish.el --- Publish blog posts from Org to the BBS site -*- lexical-binding: t; -*-
;;
;; One .org file per post. Emacs turns it into the three artifacts
;; tools/build.py consumes: post.toml, post.frag.html, and (optionally)
;; post.extra-head.html / post.extra-body.html via Babel :tangle.
;;
;; Layout on disk:
;;
;;   content/blog/<slug>/
;;     post.org              ← the only file a human edits
;;     post.toml             ← generated from #+KEYWORDS: here
;;     post.frag.html        ← generated from top-level Org headings
;;     post.extra-head.html  ← tangled from #+BEGIN_SRC html :tangle …
;;     post.extra-body.html  ← tangled from #+BEGIN_SRC html :tangle …
;;
;; Post.org shape:
;;
;;   #+TITLE: My Post
;;   #+DESCRIPTION: One-line meta description.
;;   #+CANONICAL: https://shanecurry.com/blog/my-post/
;;   #+PUBLISHED: 2026-04-19
;;   #+KIND: note
;;   #+BLURB: Short hook for the blog index.
;;
;;   * First Window
;;   Prose. Links like [[https://example.com][Example]]. Plain Org.
;;
;;   * Controls   :experiment:
;;   #+BEGIN_EXPORT html
;;   <canvas id="scene" width="640" height="360"></canvas>
;;   #+END_EXPORT
;;
;; Headings with an `experiment' tag get the yellow frame. Top-level
;; heading text becomes the window title. Headings below that level
;; render as <h3>/<h4> inside the window body.
;;
;; Commands:
;;
;;   M-x shane/export-current-post
;;       Tangle + write post.toml + write post.frag.html. No git action.
;;
;;   M-x shane/publish-current-post
;;       Export, then `git add content/ && git commit -m … && git push`.
;;       GitHub Actions rebuilds site/ and deploys. Prompts for the
;;       commit message.
;;
;; Setup: (add-to-list 'load-path "/path/to/repo/tools/emacs")
;;        (require 'shane-publish)
;;        ;; Optional: auto-bind in post.org buffers only
;;        (add-hook 'org-mode-hook
;;                  (lambda ()
;;                    (when (shane-publish--current-post-dir)
;;                      (local-set-key (kbd "C-c p e") #'shane/export-current-post)
;;                      (local-set-key (kbd "C-c p d") #'shane/publish-current-post))))

;;; Code:

(require 'org)
(require 'ox-html)
(require 'ob-tangle)

(defgroup shane-publish nil
  "Publish shanecurry.com blog posts from Org."
  :group 'org)

(defcustom shane-publish-blog-index-entries 5
  "Unused here — kept for parity with build.py menubar output."
  :type 'integer
  :group 'shane-publish)

;;; --------------------------------------------------------------------
;;; Path helpers
;;; --------------------------------------------------------------------

(defun shane-publish--current-post-dir ()
  "If the current buffer is content/**/post.org, return its directory."
  (let ((f (buffer-file-name)))
    (when (and f (string-match-p "/content/.+/post\\.org\\'" f))
      (file-name-directory f))))

(defun shane-publish--repo-root ()
  "Return the repo root for the current post."
  (let ((dir (shane-publish--current-post-dir)))
    (unless dir
      (user-error "Not visiting a content/**/post.org file"))
    (locate-dominating-file dir ".git")))

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
    (unless title
      (user-error "post.org is missing #+TITLE:"))
    (unless canonical
      (user-error "post.org is missing #+CANONICAL:"))
    (with-temp-file (expand-file-name "post.toml" dir)
      (insert (format "title = %s\n" (shane-publish--toml-string title)))
      (when description
        (insert (format "description = %s\n" (shane-publish--toml-string description))))
      (insert (format "canonical = %s\n" (shane-publish--toml-string canonical)))
      (when published
        (unless (string-match-p "\\`[0-9]\\{4\\}-[0-9]\\{2\\}-[0-9]\\{2\\}\\'" published)
          (user-error "#+PUBLISHED must be YYYY-MM-DD, got: %s" published))
        ;; TOML date literal — bare value, no quotes
        (insert (format "published = %s\n" published)))
      (when kind
        (insert (format "kind = %s\n" (shane-publish--toml-string kind))))
      (when blurb
        (insert (format "blurb = %s\n" (shane-publish--toml-string blurb)))))))

;;; --------------------------------------------------------------------
;;; Body export: each level-1 heading → one <section class="window">
;;; --------------------------------------------------------------------

(defun shane-publish--escape-html (s)
  "Minimal HTML attribute escape."
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
        (org-html-container-element "div"))
    (with-temp-buffer
      (insert s)
      (org-mode)
      ;; BODY-ONLY: org-export-as with BODY-ONLY arg = t
      (org-export-as 'html nil nil t
                     '(:with-toc nil :section-numbers nil)))))

(defun shane-publish--strip-outline-wrappers (html)
  "Org's HTML exporter wraps headings in <div class=\"outline-container-*\">.
We strip those because we wrap in <section class=\"window\"> ourselves."
  (let ((s html))
    (setq s (replace-regexp-in-string
             "<div id=\"outline-container-[^\"]*\"[^>]*>" "" s))
    (setq s (replace-regexp-in-string
             "<div class=\"outline-text-[^\"]*\"[^>]*>" "" s))
    ;; Close tags we removed (can't safely regex — HTML exporter paired
    ;; them perfectly, so closing </div>s that correspond remain; leave
    ;; them — innocuous trailing </div>s get collapsed by the browser.)
    ;; Strip Org's per-heading anchor h2.
    (setq s (replace-regexp-in-string
             "<h2[^>]*>[^<]*</h2>" "" s))
    s))

(defun shane-publish--heading-to-window (heading)
  "Return HTML for one level-1 Org HEADING as a <section class=window>."
  (let* ((title (org-element-property :raw-value heading))
         (tags  (or (org-element-property :tags heading) '()))
         (experiment (member "experiment" tags))
         (beg (org-element-property :contents-begin heading))
         (end (org-element-property :contents-end heading))
         (body-org (if (and beg end)
                       (buffer-substring-no-properties beg end)
                     ""))
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
  "Write DIR/post.frag.html: one window per top-level Org heading."
  (let* ((ast (org-element-parse-buffer))
         (level1 (org-element-map ast 'headline
                   (lambda (h)
                     (when (= 1 (org-element-property :level h)) h)))))
    (unless level1
      (user-error "post.org has no top-level `* Heading' windows"))
    (with-temp-file (expand-file-name "post.frag.html" dir)
      (dolist (h level1)
        (insert (shane-publish--heading-to-window h))
        (insert "\n")))))

;;; --------------------------------------------------------------------
;;; Top-level commands
;;; --------------------------------------------------------------------

;;;###autoload
(defun shane/export-current-post ()
  "Tangle, write post.toml, write post.frag.html for the current post.org."
  (interactive)
  (let ((dir (shane-publish--current-post-dir)))
    (unless dir
      (user-error "Not visiting a content/**/post.org file"))
    (save-buffer)
    ;; 1. Tangle any #+BEGIN_SRC :tangle blocks (experiment head/body,
    ;;    or other-file targets for /assets/<slug>/main.js etc.)
    (let ((org-confirm-babel-evaluate nil))
      (org-babel-tangle))
    ;; 2. Frontmatter
    (shane-publish--write-toml dir)
    ;; 3. Body
    (shane-publish--write-frag-html dir)
    (message "Exported %s (post.toml + post.frag.html + tangled targets)"
             (file-relative-name dir (shane-publish--repo-root)))))

;;;###autoload
(defun shane/publish-current-post (commit-msg)
  "Export the current post, then commit `content/' and push to origin.
GitHub Actions rebuilds site/ and deploys to shanecurry.com."
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
            (format "git add content/ && git commit -m %s && git push 2>&1"
                    (shell-quote-argument commit-msg)))))
      (with-current-buffer (get-buffer-create "*shane-publish*")
        (erase-buffer)
        (insert git-output)
        (display-buffer (current-buffer)))
      (message "Pushed %s — watch: https://github.com/chewgumplaygames/shanecurryblog/actions"
               commit-msg))))

(provide 'shane-publish)
;;; shane-publish.el ends here
