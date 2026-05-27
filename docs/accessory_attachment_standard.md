# Accessory Attachment Standard

Use this model for every wearable or held object. The goal is to learn placement once, save it as anchors and binding behavior, then reuse it across characters and animations.

## Core Objects

An attachment profile defines how a class of assets connects to a character. It has an `id`, `category`, keywords, anchors, placement method, binding, motion, and validation gates. Profiles live in `config/accessory_attachment_profiles.json`.

An anchor is a named 3D point plus orientation. Character anchors describe stable body locations such as `neck-chest-collar-center` or `right-hand-palm-grip`. Asset anchors describe meaningful object points such as `tie-knot-top`, `bowtie-center`, or `handle-center`.

## Placement Flow

Placement should use the working image-guided path:

```text
Qwen target image -> SAM target mask -> Blender object-mask render -> silhouette pose optimization
```

Do not move the object with OpenCV pixel transforms. OpenCV is only for metrics such as IoU, centroid distance, bounding-box error, and contour distance. The optimizer must adjust the real Blender transform: location, rotation, and scale.

## Binding & Motion

After a pose is accepted, convert it into reusable anchors. Worn flexible items use `skinned_weighted` binding, for example a tie bound to spine/chest/neck. Rigid worn items use `rigid_parent`, for example glasses attached to the head. Held props use `rigid_socket` with optional `socket_swing`, so a briefcase follows the hand and swings around its handle.

## Validation

Every profile declares required views and checks. Validate front and angled views for neck/chest items, back and side views for backpacks, and close hand views for held props. A placement is not reusable until it passes mask IoU, collision, floating, offscreen, and depth checks for its profile.

## Extension Rules

Add a new profile before adding one-off placement code. Name profiles as `<category>.<asset_class>`, for example `hand_held.briefcase`. Add keywords for classification, define both character and asset anchors, choose a binding mode, and set the validation views that prove it works in 3D.
