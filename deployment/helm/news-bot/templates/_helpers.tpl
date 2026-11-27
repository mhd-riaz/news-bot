{{/*
Names. The full name is the release name, or "<release>-news-bot" when the release
name does not already contain "news-bot".
*/}}
{{- define "news-bot.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "news-bot.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 40 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 40 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 40 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{- define "news-bot.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/* Labels on every object. Call with (dict "root" $ "component" "web"). */}}
{{- define "news-bot.labels" -}}
helm.sh/chart: {{ include "news-bot.chart" .root }}
{{ include "news-bot.selectorLabels" . }}
app.kubernetes.io/version: {{ .root.Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .root.Release.Service }}
app.kubernetes.io/part-of: news-bot
{{- end }}

{{- define "news-bot.selectorLabels" -}}
app.kubernetes.io/name: {{ include "news-bot.name" .root }}
app.kubernetes.io/instance: {{ .root.Release.Name }}
app.kubernetes.io/component: {{ .component }}
{{- end }}

{{/* An image reference. Call with (dict "root" $ "image" .Values.web.image). */}}
{{- define "news-bot.image" -}}
{{- $registry := .root.Values.images.registry | default "" | trimSuffix "/" }}
{{- $tag := .image.tag | default .root.Values.images.tag | toString }}
{{- if $registry }}
{{- printf "%s/%s:%s" $registry .image.repository $tag }}
{{- else }}
{{- printf "%s:%s" .image.repository $tag }}
{{- end }}
{{- end }}

{{/* Pod settings shared by every app pod: no service-account token, no service
links (they would add NEWS_BOT_* variables), image pull secrets and placement. */}}
{{- define "news-bot.podBasics" -}}
automountServiceAccountToken: false
enableServiceLinks: false
{{- with .Values.images.pullSecrets }}
imagePullSecrets:
  {{- range . }}
  - name: {{ . }}
  {{- end }}
{{- end }}
{{- with .Values.nodeSelector }}
nodeSelector:
  {{- toYaml . | nindent 2 }}
{{- end }}
{{- with .Values.tolerations }}
tolerations:
  {{- toYaml . | nindent 2 }}
{{- end }}
{{- end }}

{{/* The pod security context for the app images, which run as user 10001. */}}
{{- define "news-bot.podSecurity" -}}
securityContext:
  runAsNonRoot: true
  runAsUser: {{ .uid | default 10001 }}
  runAsGroup: {{ .uid | default 10001 }}
  fsGroup: {{ .uid | default 10001 }}
  fsGroupChangePolicy: OnRootMismatch
  seccompProfile:
    type: RuntimeDefault
{{- end }}

{{/* The container security context: read-only files, no Linux capabilities. */}}
{{- define "news-bot.containerSecurity" -}}
securityContext:
  allowPrivilegeEscalation: false
  readOnlyRootFilesystem: true
  capabilities:
    drop: [ALL]
{{- end }}

{{/* host:port list of MongoDB, inside or outside the cluster. */}}
{{- define "news-bot.mongoHosts" -}}
{{- if .Values.mongo.enabled }}
{{- printf "%s-mongo:27017" (include "news-bot.fullname" .) }}
{{- else }}
{{- required "mongo.external.hosts is required when mongo.enabled is false" .Values.mongo.external.hosts }}
{{- end }}
{{- end }}

{{/*
Environment variables for one MongoDB login: the password from the Secret, then
the URI built from it. Kubernetes replaces $(NAME) with a variable defined earlier
in the same list, so the password never appears in the chart or its values.
Call with (dict "root" $ "user" "collector" "uriVar" "NEWS_MONGO_URI").
*/}}
{{- define "news-bot.mongoLoginEnv" -}}
{{- $passwordVar := printf "NEWS_MONGO_%s_PASSWORD" (upper .user) }}
{{- $database := .root.Values.mongo.database }}
{{- $options := printf "authSource=%s" $database }}
{{- if and (not .root.Values.mongo.enabled) .root.Values.mongo.external.options }}
{{- $options = printf "%s&%s" $options .root.Values.mongo.external.options }}
{{- end -}}
- name: {{ $passwordVar }}
  valueFrom:
    secretKeyRef:
      name: {{ .root.Values.secret.name }}
      key: {{ $passwordVar }}
- name: {{ .uriVar }}
  value: {{ printf "mongodb://%s:$(%s)@%s/?%s" .user $passwordVar (include "news-bot.mongoHosts" .root) $options | quote }}
{{- end }}

{{/*
An init container that waits until this pod's MongoDB login works. The users Job
creates the logins just after an install, so the app does not crash and restart
while it waits. Call with (dict "root" $ "user" "reader").
*/}}
{{- define "news-bot.waitForMongo" -}}
- name: wait-for-database
  image: {{ .root.Values.mongo.image }}
  imagePullPolicy: IfNotPresent
  command:
    - /bin/sh
    - -c
    - |
      tries=0
      until mongosh "$MONGO_URI" --quiet --norc --eval 'db.runCommand({ ping: 1 }).ok' > /dev/null 2>&1; do
        tries=$((tries + 1))
        echo "Waiting for the MongoDB login '{{ .user }}' (the users job makes it). Try $tries."
        sleep 5
      done
      echo "The MongoDB login '{{ .user }}' works."
  env:
    - name: HOME
      value: /tmp
    {{- include "news-bot.mongoLoginEnv" (dict "root" .root "user" .user "uriVar" "MONGO_URI") | nindent 4 }}
  {{- include "news-bot.containerSecurity" . | nindent 2 }}
  resources:
    requests: {cpu: 10m, memory: 64Mi}
    limits: {memory: 256Mi}
  volumeMounts:
    - name: tmp
      mountPath: /tmp
{{- end }}

{{/* A Secret value as an environment variable. Call with (dict "root" $ "name" "X" "key" "Y" "optional" true). */}}
{{- define "news-bot.secretEnv" -}}
- name: {{ .name }}
  valueFrom:
    secretKeyRef:
      name: {{ .root.Values.secret.name }}
      key: {{ .key | default .name }}
      {{- if .optional }}
      optional: true
      {{- end }}
{{- end }}

{{/* Settings that would be unsafe together stop the install with a clear message. */}}
{{- define "news-bot.checks" -}}
{{- if not (has .Values.environment (list "development" "staging" "production")) }}
{{- fail "environment must be development, staging or production" }}
{{- end }}
{{- if not .Values.web.signIn }}
{{- if ne .Values.environment "development" }}
{{- fail "web.signIn may be false only with environment: development (a test on your own computer)" }}
{{- end }}
{{- if or .Values.ingress.enabled .Values.cloudflared.enabled }}
{{- fail "web.signIn is false, so the reader app must not be published: turn off ingress and cloudflared" }}
{{- end }}
{{- end }}
{{- if and .Values.ingress.enabled (not .Values.web.publicUrl) }}
{{- fail "web.publicUrl is required when ingress.enabled is true: the ingress uses its host name" }}
{{- end }}
{{- end }}
